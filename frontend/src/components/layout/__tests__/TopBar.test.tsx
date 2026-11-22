import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { setAtlasGen } from "@/api/Http";
import { TopBar } from "@/components/layout/TopBar";
import { TimelapseTab } from "@/components/replay/TimelapseTab";
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
		expect(screen.getByRole("button", { name: /Check update.*1\.17/i })).toBeInTheDocument(); // (the update pill)
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

	it("the map tools: a tab starts its tool, lit while on; clicked again (or Select) it ends (user's design)", async () => {
		const { user } = renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		expect(screen.getByRole("button", { name: "Select" })).toHaveAttribute("aria-pressed", "true");
		await user.click(screen.getByRole("button", { name: "Biome" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "lasso" });
		expect(screen.getByRole("button", { name: "Biome" })).toHaveAttribute("aria-pressed", "true");
		expect(screen.getByRole("button", { name: "Select" })).toHaveAttribute("aria-pressed", "false");
		await user.click(screen.getByRole("button", { name: "Biome" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
		await user.click(screen.getByRole("button", { name: "I'm here" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "player" });
		await user.click(screen.getByRole("button", { name: "Select" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("no map mode while the timelapse is open: opening it ends one, and Route can't start in it", async () => {
		const { user } = renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		await user.click(screen.getByRole("button", { name: "Route" }));
		expect(screen.getByRole("button", { name: "Route" })).toHaveAttribute("aria-pressed", "true");
		act(() => useAppStore.getState().setReplay({} as never));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
		expect(screen.getByRole("button", { name: "Route" })).toBeDisabled();
		act(() => useAppStore.getState().setMode({ kind: "route", from: null }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("quitting asks first", async () => {
		const { user } = renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		await user.click(screen.getByRole("button", { name: "File" }));
		await user.click(await screen.findByRole("menuitem", { name: "Quit the app" }));
		expect(useAppStore.getState().confirm?.title).toBe("Quit");
	});

	it("Fix seams during adding asks to queue it, only for the atlas it was asked for", async () => {
		// (CodeRabbit: the box and its Queue acted on an atlas opened meanwhile)
		setAtlasGen(1);
		let switchFirst = false;
		const { user, calls } = renderWithApp(<TopBar />, {
			"GET /api/atlases": atlases,
			"POST /api/seams": (b: unknown) => {
				if (switchFirst) setAtlasGen(2);
				return (b as { after_adding: boolean }).after_adding
					? { ok: true, adding: false, queued: true }
					: { ok: false, adding: true, queued: false };
			},
		});
		await user.click(screen.getByRole("button", { name: "File" }));
		await user.click(await screen.findByRole("menuitem", { name: "Fix seams (clean map)" }));
		await waitFor(() => expect(useAppStore.getState().confirm?.yes).toBe("Queue"));
		useAppStore.getState().confirm?.onYes();
		await waitFor(() => expect(calls.filter((c) => c.path === "/api/seams")).toHaveLength(2));
		act(() => useAppStore.getState().askConfirm(null));
		switchFirst = true; // another atlas opens while it is asked
		await user.click(screen.getByRole("button", { name: "File" }));
		await user.click(await screen.findByRole("menuitem", { name: "Fix seams (clean map)" }));
		await waitFor(() => expect(calls.filter((c) => c.path === "/api/seams")).toHaveLength(3));
		expect(useAppStore.getState().confirm).toBeNull(); // (no box for the atlas before)
	});

	it("Replay left the top bar: the Timelapse tab on the map opens it at its end, and closes it (user)", async () => {
		renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		expect(screen.queryByRole("button", { name: "Replay" })).not.toBeInTheDocument();
	});
});

describe("TimelapseTab", () => {
	afterEach(resetStore);

	it("opens the timelapse at its end, lit while open, and closes it again", async () => {
		const { user, calls } = renderWithApp(<TimelapseTab />, {
			"POST /api/replay/open": plan,
			"POST /api/replay/close": { ok: true },
		});
		const tab = screen.getByRole("button", { name: /Timelapse/ });
		expect(tab).toHaveAttribute("aria-pressed", "false");
		await user.click(tab);
		await waitFor(() => expect(useAppStore.getState().replay).toMatchObject({ pos: 4, playing: false }));
		expect(tab).toHaveAttribute("aria-pressed", "true");
		await user.click(tab);
		expect(useAppStore.getState().replay).toBeNull();
		await waitFor(() => expect(calls.some((c) => c.path === "/api/replay/close")).toBe(true));
	});

	it("none for an atlas without screenshots", () => {
		renderWithApp(<TimelapseTab />, {
			"GET /api/state": { ...state, atlas: state.atlas && { ...state.atlas, shots: 0 } },
		});
		expect(screen.queryByRole("button", { name: /Timelapse/ })).not.toBeInTheDocument();
	});
});
