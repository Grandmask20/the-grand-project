import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { setAtlasGen } from "@/api/Http";
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

	it("shows the atlas menu, the map tools and the version (the atlas's numbers are in the status line)", () => {
		renderWithApp(<TopBar />, { "GET /api/atlases": atlases });
		expect(screen.getByRole("button", { name: /Check update.*1\.17/i })).toBeInTheDocument(); // (the update pill)
		expect(screen.getByRole("button", { name: /Atlas: default/ })).toBeInTheDocument();
		expect(screen.getByRole("toolbar", { name: "Map tools" })).toBeInTheDocument();
		expect(screen.queryByText(/80 maps · 9 icons/)).toBeNull();
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
});
