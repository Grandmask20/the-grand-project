import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapMenu } from "@/components/map/MapMenu";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAppStore } from "@/store/AppStore";
import { meta, nodeInfo } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

const graph = { nodes: [{ id: 12, x: 440, y: 200, icons: [], status: "" }], edges: [] };
const landmark: ItemInfo = {
	...nodeInfo,
	kind: "landmark",
	id: 4,
	title: "City",
	landmark_kind: "City",
	city_type: "Vaal",
	node: null,
};
const bookmark: ItemInfo = { ...nodeInfo, kind: "bookmark", id: 9, name: "farm", group: "Farm", node: null };

function menu(hit: ItemInfo | null, debug = false, routes: Record<string, unknown> = {}) {
	const onClose = vi.fn();
	const view = renderWithApp(
		<MapMenu x={10} y={20} at={[1, 2]} hit={hit} meta={meta} debug={debug} onClose={onClose} />,
		{ "GET /api/graph": graph, ...routes },
	);
	return { ...view, onClose };
}

/** Opens a submenu (Radix opens one with the arrow key on its trigger). */
async function sub(user: ReturnType<typeof menu>["user"], name: RegExp | string) {
	const trigger = screen.getByRole("menuitem", { name });
	trigger.focus();
	await user.keyboard("{ArrowRight}");
}

describe("MapMenu", () => {
	it("on empty ground: a bookmark or the screenshots of the spot", async () => {
		const { user } = menu(null);
		expect(screen.queryByText("I'm here")).toBeNull();
		await user.click(screen.getByRole("menuitem", { name: "Add bookmark here…" }));
		expect(useAppStore.getState().bookmarkEdit).toMatchObject({ id: null, x: 1, y: 2, group: "Other" });
	});

	it("shows the screenshots of the spot", async () => {
		const { user } = menu(null);
		await user.click(screen.getByRole("menuitem", { name: "Screenshots of this spot" }));
		expect(useAppStore.getState().sources).toEqual([1, 2]);
	});

	it("on a map: bookmark it with its suggested name", async () => {
		const { user } = menu(nodeInfo);
		await user.click(screen.getByRole("menuitem", { name: "Bookmark this…" }));
		expect(useAppStore.getState().bookmarkEdit).toMatchObject({ name: "Breach", group: "Breach", x: 440 });
	});

	it("on a map: you are here", async () => {
		const { user, calls, queryClient } = menu(nodeInfo, false, { "PATCH /api/settings": (b: unknown) => b });
		// (the map graph in first: your position is its map's)
		await waitFor(() =>
			expect(calls.some((c) => c.path === "/api/graph") && queryClient.isFetching() === 0).toBe(true),
		);
		await user.click(screen.getByRole("menuitem", { name: "I'm here" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/settings")?.body).toMatchObject({ ui: { player: { node: 12 } } }),
		);
	});

	it("on a map: this map is a landmark", async () => {
		const { user, calls } = menu(nodeInfo, false, { "POST /api/landmark": { ok: true } });
		await sub(user, "This map is a…");
		await user.click(await screen.findByRole("menuitem", { name: "Tower" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/landmark")?.body).toEqual({ x: 440, y: 200, kind: "Tower", on: "map" }),
		);
	});

	it("on a landmark: change its kind, delete it after asking, set a city's type", async () => {
		const { user, calls } = menu(landmark, false, {
			"POST /api/landmark": { ok: true },
			"POST /api/city-type": { ok: true },
		});
		await sub(user, "Change to");
		expect(await screen.findByRole("menuitem", { name: "● City" })).toBeInTheDocument();
		await user.click(screen.getByRole("menuitem", { name: "Hall" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/landmark")?.body).toMatchObject({ kind: "Hall" }));
	});

	it("on a landmark: delete asks first", async () => {
		const { user, calls } = menu(landmark, false, { "POST /api/landmark": { ok: true } });
		await user.click(screen.getByRole("menuitem", { name: "Delete landmark" }));
		const ask = useAppStore.getState().confirm;
		expect(ask?.text).toContain("Delete this City?");
		ask?.onYes();
		await waitFor(() => expect(calls.find((c) => c.path === "/api/landmark")?.body).toMatchObject({ kind: "" }));
	});

	it("on a removed landmark: restore it", async () => {
		const { user, calls } = menu({ ...landmark, removed: true }, false, { "POST /api/landmark": { ok: true } });
		await user.click(screen.getByRole("menuitem", { name: "Restore landmark" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/landmark")?.body).toMatchObject({ kind: "City" }));
	});

	it("on a city: its type, or automatic", async () => {
		const { user, calls } = menu(landmark, false, { "POST /api/city-type": { ok: true } });
		await sub(user, "City type");
		expect(await screen.findByRole("menuitem", { name: "● Vaal" })).toBeInTheDocument();
		await user.click(screen.getByRole("menuitem", { name: "Automatic" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/city-type")?.body).toEqual({ id: 4, type: null }));
	});

	it("on a bookmark: edit it, or delete it after asking", async () => {
		const { user, calls } = menu(bookmark, false, { "POST /api/bookmarks/delete": { deleted: ["farm"] } });
		expect(screen.getByRole("menuitem", { name: "Edit bookmark…" })).toBeInTheDocument();
		await user.click(screen.getByRole("menuitem", { name: "Delete bookmark" }));
		useAppStore.getState().confirm?.onYes();
		await waitFor(() => expect(calls.find((c) => c.path === "/api/bookmarks/delete")?.body).toEqual({ ids: [9] }));
	});

	it("debug: marks with a note, and a missing path from here", async () => {
		const debug = {
			enabled: true,
			marks: [],
			file: "",
			reasons: { "wrong map": ["not a map"], "missing map": ["hidden"], "wrong path": ["no path"] },
		};
		const { user, calls } = menu(nodeInfo, true, {
			"GET /api/debug": debug,
			"POST /api/debug": { id: 1 },
		});
		await sub(user, "Debug");
		await user.click(await screen.findByRole("menuitem", { name: "Map: not a map…" }));
		const ask = useAppStore.getState().prompt;
		expect(ask?.label).toContain("Map: not a map");
		ask?.onOk("looks wrong");
		await waitFor(() =>
			expect(calls.find((c) => c.method === "POST" && c.path === "/api/debug")?.body).toEqual({
				kind: "wrong map",
				reason: "not a map",
				note: "looks wrong",
				maps: [12],
			}),
		);
	});

	it("debug: a missing path waits for the other map", async () => {
		const debug = { enabled: true, marks: [], file: "", reasons: {} };
		const { user } = menu(nodeInfo, true, { "GET /api/debug": debug });
		await sub(user, "Debug");
		await user.click(await screen.findByRole("menuitem", { name: /Missing path from here/ }));
		useAppStore.getState().prompt?.onOk("n");
		await waitFor(() => expect(useAppStore.getState().mode).toEqual({ kind: "debug-link", from: 12, note: "n" }));
	});
});
