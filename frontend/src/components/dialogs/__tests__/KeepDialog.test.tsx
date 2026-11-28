import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KeepDialog } from "@/components/dialogs/KeepDialog";
import type { KeepInfo } from "@/domain/app/KeepInfo";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp } from "@/test/RenderWithApp";

const info: KeepInfo = { shots: 40, copied: 10, todo: 28, lost: 2, move: 25, mb: 22.4, seconds: 10 };

function open(over: Partial<KeepInfo> = {}) {
	const r = renderWithApp(<KeepDialog />, {
		"GET /api/atlas/keep-info": { ...info, ...over },
		"POST /api/atlas/keep": { ok: true },
	});
	act(() => useAppStore.getState().askKeep(true));
	return r;
}

describe("KeepDialog (screenshots safe to delete: user's design)", () => {
	it("says what it keeps, what moves and what is lost already", async () => {
		open();
		expect(
			await screen.findByText("40 screenshots: 10 copied already, 28 to copy (about 22.4 MB, under a minute)"),
		).toBeInTheDocument();
		expect(screen.getByText("25 move to the used folder")).toBeInTheDocument();
		expect(screen.getByText(/2 are gone and had no copy/)).toBeInTheDocument();
	});

	it("asks first, then starts the job and closes (long work asks first: user)", async () => {
		const { user, calls } = open();
		await user.click(await screen.findByRole("button", { name: "Keep copies" }));
		await waitFor(() => expect(calls.some((c) => c.path === "/api/atlas/keep")).toBe(true));
		expect(useAppStore.getState().keepCopies).toBe(false);
	});

	it("with everything kept already, says so and offers nothing to start", async () => {
		open({ copied: 40, todo: 0, lost: 0, move: 0, mb: 0, seconds: 0 });
		expect(await screen.findByText("Everything is kept already.")).toBeInTheDocument();
		expect(screen.queryByRole("button", { name: "Keep copies" })).toBeNull();
	});

	it("is about the open atlas: another opening closes it", () => {
		act(() => useAppStore.getState().askKeep(true));
		act(() => useAppStore.getState().resetAtlas());
		expect(useAppStore.getState().keepCopies).toBe(false);
	});
});
