import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { TopBar } from "@/components/layout/TopBar";
import { useAppStore } from "@/store/AppStore";
import { atlases, state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const plan = {
	n_steps: 4,
	settings: {},
	kind: "add",
	area: false,
	step_of: [],
	ticks: [],
	step_time: [],
	step_session: [],
	real: "",
	real_seconds: 0,
};

describe("TopBar", () => {
	afterEach(resetStore);

	it("shows the atlas's numbers and the version", () => {
		renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		expect(screen.getByText(/80 maps · 9 icons · 4 landmarks · 4\s+screenshots/)).toBeInTheDocument();
		expect(screen.getByText("v1.17")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: /Atlas: default/ })).toBeInTheDocument();
	});

	it("undo asks first, naming the screenshots", async () => {
		const { user, calls } = renderWithApp(<TopBar />, {
			"GET /api/atlases": atlases,
			"POST /api/undo": { names: ["shot_3.png"] },
		});
		await user.click(screen.getByRole("button", { name: "Undo" }));
		const ask = useAppStore.getState().confirm;
		expect(ask?.text).toContain("shot_3.png");
		ask?.onYes();
		await waitFor(() => expect(calls.some((c) => c.path === "/api/undo")).toBe(true));
	});

	it("nothing to undo, or busy: no undo", () => {
		renderWithApp(<TopBar />, { "GET /api/state": { ...state, busy: true }, "GET /api/atlases": atlases });
		expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
	});

	it("Biome select switches the lasso on, and says End while on (user: only Esc ended it)", async () => {
		const { user } = renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		await user.click(screen.getByRole("button", { name: "Biome select" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "lasso" });
		await user.click(screen.getByRole("button", { name: "End biome select" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("no map mode while the timelapse is open: opening it ends one, and Route can't start in it", async () => {
		const { user } = renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		await user.click(screen.getByRole("button", { name: "Route" }));
		expect(screen.getByRole("button", { name: "End route" })).toBeInTheDocument();
		act(() => useAppStore.getState().setReplay({} as never));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
		expect(screen.getByRole("button", { name: "Route" })).toBeDisabled();
		act(() => useAppStore.getState().setMode({ kind: "route", from: null }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("replay opens at its end, and closes again", async () => {
		const { user, calls } = renderWithApp(<TopBar />, {
			"GET /api/atlases": atlases,
			"POST /api/replay/open": plan,
			"POST /api/replay/close": { ok: true },
		});
		await user.click(screen.getByRole("button", { name: "Replay" }));
		await waitFor(() => expect(useAppStore.getState().replay).toMatchObject({ pos: 4, playing: false }));
		await user.click(screen.getByRole("button", { name: "Replay" }));
		expect(useAppStore.getState().replay).toBeNull();
		await waitFor(() => expect(calls.some((c) => c.path === "/api/replay/close")).toBe(true));
	});

	it("no replay for an atlas without screenshots", () => {
		renderWithApp(<TopBar />, {
			"GET /api/state": { ...state, atlas: state.atlas && { ...state.atlas, shots: 0 } },
			"GET /api/atlases": atlases,
		});
		expect(screen.getByRole("button", { name: "Replay" })).toBeDisabled();
	});

	it("quitting asks first", async () => {
		const { user } = renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		await user.click(screen.getByRole("button", { name: "File" }));
		await user.click(await screen.findByRole("menuitem", { name: "Quit the app" }));
		expect(useAppStore.getState().confirm?.title).toBe("Quit");
	});
});
