import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RouteTab } from "@/components/route/RouteTab";
import { useAppStore } from "@/store/AppStore";
import { state, types } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const graph = {
	nodes: [
		{ id: 12, x: 440, y: 200, icons: ["MapBoss", "Breach"], status: "confirmed" },
		{ id: 13, x: 500, y: 200, icons: [], status: "confirmed" },
	],
	edges: [{ a: 12, b: 13 }],
};
const withPlayer = {
	...state,
	settings: { ...state.settings, ui: { player: { x: 440, y: 200, node: 12, atlas: state.atlas?.path } } },
};

describe("RouteTab", () => {
	afterEach(resetStore);

	it("asks where you are until it is set", async () => {
		const { user } = renderWithApp(<RouteTab />, { "GET /api/graph": graph, "GET /api/types": types });
		expect(screen.getByText("not set")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Set my position" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "player" });
		expect(screen.getByText(/Click the map you are on/)).toBeInTheDocument();
	});

	it("shows your map and goes there", async () => {
		const { user } = renderWithApp(<RouteTab />, {
			"GET /api/state": withPlayer,
			"GET /api/graph": graph,
			"GET /api/types": types,
		});
		expect(screen.getByText("map #12")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Go there" }));
		expect(useAppStore.getState().fly).toMatchObject({ x: 440, y: 200, px: 0.5 });
	});

	it("forgets your position (an I'm here by mistake)", async () => {
		const { user, calls } = renderWithApp(<RouteTab />, {
			"GET /api/state": withPlayer,
			"GET /api/graph": graph,
			"GET /api/types": types,
			"PATCH /api/settings": { ...state.settings, ui: { player: null } },
		});
		await user.click(screen.getByRole("button", { name: "Forget my position" }));
		await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ ui: { player: null } }));
		expect(await screen.findByText("not set")).toBeInTheDocument();
	});

	it("a position set in another atlas is not yours here", () => {
		const elsewhere = {
			...state,
			settings: { ...state.settings, ui: { player: { x: 1, y: 1, node: 1, atlas: "/other/atlas.json" } } },
		};
		renderWithApp(<RouteTab />, { "GET /api/state": elsewhere, "GET /api/graph": graph, "GET /api/types": types });
		expect(screen.getByText("not set")).toBeInTheDocument();
	});

	it("a route tracked: maps left, its maps, and Stop tracking", async () => {
		useAppStore.getState().setRoute({ path: [12, 13], message: "1 map left", at: 0 });
		const { user } = renderWithApp(<RouteTab />, {
			"GET /api/state": withPlayer,
			"GET /api/graph": graph,
			"GET /api/types": types,
		});
		expect(screen.getByText("1 map left")).toBeInTheDocument();
		await waitFor(() => expect(screen.getByRole("button", { name: /map #13/ })).toBeInTheDocument());
		await user.click(screen.getByRole("button", { name: /map #13/ }));
		expect(useAppStore.getState().fly).toMatchObject({ x: 500, y: 200 });
		await user.click(screen.getByRole("button", { name: "Stop tracking" }));
		expect(useAppStore.getState().route).toBeNull();
	});

	it("the tracked route's maps as steps: the start, where you are, the next one; the ones run struck through", async () => {
		useAppStore.getState().setRoute({ path: [12, 13], message: "1 map left", at: 0 });
		renderWithApp(<RouteTab />, { "GET /api/state": withPlayer, "GET /api/graph": graph, "GET /api/types": types });
		const steps = await screen.findByRole("list", { name: "The route's maps" });
		await waitFor(() => expect(steps.querySelectorAll("li")).toHaveLength(2));
		expect(steps.textContent).toMatch(/map #12 · start/);
		expect(screen.getByText("next")).toBeInTheDocument();
		act(() => useAppStore.getState().setRoute({ path: [12, 13], message: "there", at: 1 }));
		expect(screen.queryByText("next")).toBeNull();
		expect(
			within(steps)
				.getByText(/map #12/)
				.closest("span"),
		).toHaveClass("line-through");
	});

	it("the nearest map with an icon is tracked, as a route from Route in the top bar is (user)", async () => {
		const { user } = renderWithApp(<RouteTab />, {
			"GET /api/state": {
				...withPlayer,
				settings: { ...withPlayer.settings, ui: { player: { x: 500, y: 200, node: 13, atlas: state.atlas?.path } } },
			},
			"GET /api/graph": graph,
			"GET /api/types": types,
		});
		await waitFor(() => expect(screen.getByText("map #13")).toBeInTheDocument());
		await user.click(screen.getByRole("combobox", { name: "Route to the nearest" }));
		await user.click(await screen.findByRole("option", { name: "Breach" }));
		await waitFor(() => expect(useAppStore.getState().route).toMatchObject({ path: [13, 12], at: 0 }));
		expect(screen.getByRole("button", { name: "Next map" })).toBeInTheDocument();
	});
});
