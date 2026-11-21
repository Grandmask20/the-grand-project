import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { QuestionDialog } from "@/components/dialogs/QuestionDialog";
import type { AppState } from "@/domain/app/AppState";
import type { Question } from "@/domain/app/Question";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

const TITLE = "Re-check atlas has finished";

const recheck: Question = {
	id: 9,
	question: "Here are the map changes. Choose which to keep.",
	preview: null,
	labels: { title: TITLE, yes: "Apply" },
	choices: {
		groups: [
			{
				id: "maps",
				name: "Maps",
				count: 3,
				added: 1,
				removed: 1,
				changed: 1,
				items: [
					{ text: "Map #3 removed", x: 600, y: 0, kind: "removed" },
					{ text: "New map", x: 900, y: 10, kind: "added" },
				],
				ticked: true,
			},
			{ id: "paths", name: "Paths", count: 0, added: 0, removed: 0, changed: 0, items: [], ticked: false },
			{
				id: "biomes",
				name: "Biomes",
				count: 1,
				added: 1,
				removed: 0,
				changed: 0,
				items: [{ text: "Map #0: no biome → Vaal city", x: 0, y: 0, kind: "added" }],
				ticked: true,
			},
		],
	},
};

function open() {
	const r = renderWithApp(<QuestionDialog />, { "POST /api/questions/9": { ok: true } });
	r.queryClient.setQueryData<AppState>(AppQueryKeys.state, { ...state, questions: [recheck] });
	return r;
}

describe("ChoicesDialog", () => {
	it("shows each group's +added / −removed and sends the groups kept", async () => {
		const { user, calls } = open();
		expect(await screen.findByText(TITLE)).toBeInTheDocument();
		expect(screen.getByText("~1")).toBeInTheDocument(); // (maps: +1 −1 ~1)
		expect(screen.getAllByText("+1")).toHaveLength(2);
		expect(screen.getByText("no changes")).toBeInTheDocument();
		expect(screen.getByRole("checkbox", { name: "Paths" })).toBeDisabled(); // (nothing to update)
		await user.click(screen.getByRole("checkbox", { name: "Biomes" }));
		expect(screen.getByText(/stays as before/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Apply" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/questions/9")?.body).toEqual({ yes: true, picked: ["maps"] }),
		);
	});

	it("lists a group's changes and shows each one's spot on the map", async () => {
		const { user } = open();
		expect(await screen.findByText("Map #3 removed")).toBeInTheDocument(); // (the first group with changes)
		expect(screen.getByText("…and 1 more")).toBeInTheDocument(); // (3 counted, 2 listed)
		await user.click(screen.getByRole("button", { name: "Show what changed in Biomes" }));
		expect(screen.getByText("Map #0: no biome → Vaal city")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Show what changed in Maps" }));
		await user.click(screen.getByText("New map"));
		expect(useAppStore.getState().fly).toMatchObject({ x: 900, y: 10 });
		expect(useAppStore.getState().goto).toEqual([900, 10]); // (marked: a map it adds isn't drawn yet)
		await user.click(screen.getByRole("button", { name: "Apply" }));
		expect(useAppStore.getState().goto).toBeNull();
	});

	it("isn't closed by Escape: only Apply answers it", async () => {
		const { user, calls } = open();
		await screen.findByText(TITLE);
		await user.keyboard("{Escape}");
		expect(screen.getByText(TITLE)).toBeInTheDocument();
		expect(calls.some((c) => c.path === "/api/questions/9")).toBe(false);
	});
});
