import { act, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAdjustRoute } from "@/hooks/map/UseAdjustRoute";
import type { Point } from "@/logic/Geo";
import { type MapMode, useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

// maps 1 - 2 - 3 - 4 in a row; a saved route 1 - 2 - 3
const graph = {
	nodes: [1, 2, 3, 4].map((id) => ({ id, x: id * 100, y: 0, icons: [], status: "confirmed" })),
	edges: [
		{ a: 1, b: 2 },
		{ a: 2, b: 3 },
		{ a: 3, b: 4 },
	],
};
const spots = (ids: number[]) => ids.map((id) => [id * 100, 0] as [number, number]);
const saved = {
	groups: [
		{
			name: "Routes",
			hidden: false,
			items: [
				{
					id: 5,
					name: "route1",
					note: "",
					x: 100,
					y: 0,
					created: "",
					hidden: false,
					shown: true,
					route: { from: 1, to: 3, maps: 2, legs: [{ maps: spots([1, 2, 3]), line: spots([1, 2, 3]) }] },
				},
			],
		},
	],
};

let adjust: ReturnType<typeof useAdjustRoute> = async () => {};
function Probe({ pick }: { pick: (at: Point) => Promise<ItemInfo | null> }) {
	adjust = useAdjustRoute(pick);
	return null;
}

describe("useAdjustRoute", () => {
	afterEach(resetStore);

	it("runs the clicks in their order: an add that waits longer still lands before a later remove (CodeRabbit)", async () => {
		// the add's pick answers last (map 4), the remove's at once (map 3)
		let answerAdd: ((v: ItemInfo | null) => void) | null = null;
		const pick = (at: Point) =>
			at[0] === 400
				? new Promise<ItemInfo | null>((r) => {
						answerAdd = r;
					})
				: Promise.resolve({ kind: "node", id: 3 } as ItemInfo);
		const sent: unknown[] = [];
		renderWithApp(<Probe pick={pick} />, {
			"GET /api/bookmarks": saved,
			"GET /api/graph": graph,
			"POST /api/bookmarks/route": (b: { route: unknown }) => {
				sent.push(b.route);
				return { ok: true };
			},
		});
		const mode: MapMode = { kind: "route-edit", id: 5 };
		act(() => useAppStore.getState().setMode(mode));
		await waitFor(() => expect(adjust).toBeTypeOf("function"));
		let done: Promise<unknown> = Promise.resolve();
		await act(async () => {
			const first = adjust([400, 0], true, mode, 1);
			const second = adjust([300, 0], false, mode, 1);
			await waitFor(() => expect(answerAdd).not.toBeNull()); // (the add's pick asked: answered last)
			answerAdd?.({ kind: "node", id: 4 } as ItemInfo);
			done = Promise.all([first, second]);
			await done;
		});
		// [1,2,3] + 4, then 3 off with the side past it: [1,2]
		const last = sent[sent.length - 1] as { legs: { maps: [number, number][] }[] };
		expect(sent).toHaveLength(2);
		expect(last.legs[0].maps).toEqual(spots([1, 2]));
	});

	it("an edit left behind by Esc isn't made", async () => {
		const sent: unknown[] = [];
		renderWithApp(<Probe pick={async () => ({ kind: "node", id: 4 }) as ItemInfo} />, {
			"GET /api/bookmarks": saved,
			"GET /api/graph": graph,
			"POST /api/bookmarks/route": (b: unknown) => sent.push(b),
		});
		const mode: MapMode = { kind: "route-edit", id: 5 };
		act(() => useAppStore.getState().setMode(mode));
		await act(async () => {
			const job = adjust([400, 0], true, mode, 1);
			useAppStore.getState().setMode({ kind: "normal" });
			await job;
		});
		expect(sent).toEqual([]);
	});
});
