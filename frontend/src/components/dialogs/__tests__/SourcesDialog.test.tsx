import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/Http";
import { SourcesDialog } from "@/components/dialogs/SourcesDialog";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const shots = [
	{ name: "best.png", w: 1920, h: 1080, px: 960, py: 540, exists: true },
	{ name: "gone.png", w: 1920, h: 1080, px: 100, py: 100, exists: false },
];

describe("SourcesDialog", () => {
	afterEach(resetStore);

	it("shows nothing until a spot is asked for", () => {
		renderWithApp(<SourcesDialog />);
		expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
	});

	it("shows the best screenshot first with the spot circled, and says when one is missing", async () => {
		useAppStore.getState().showSources([440.4, 199.6]);
		const { user, calls } = renderWithApp(<SourcesDialog />, { "GET /api/sources": shots });
		expect(screen.getByRole("dialog", { name: "Screenshots of 440, 200" })).toBeInTheDocument();
		const img = await screen.findByRole("img", { name: "best.png" });
		expect(img.getAttribute("src")).toBe("/api/screenshot/best.png?w=1600");
		expect(calls.find((c) => c.path === "/api/sources")?.params).toEqual({ x: 440.4, y: 199.6 });
		await user.click(screen.getByRole("button", { name: "gone.png" }));
		expect(screen.getByText("missing file: gone.png")).toBeInTheDocument();
	});

	it("says when no screenshot covers the spot", async () => {
		useAppStore.getState().showSources([0, 0]);
		renderWithApp(<SourcesDialog />, { "GET /api/sources": [] });
		expect(await screen.findByText("No screenshot covers that spot.")).toBeInTheDocument();
	});

	it("says when the list failed", async () => {
		useAppStore.getState().showSources([0, 0]);
		renderWithApp(<SourcesDialog />, { "GET /api/sources": new ApiError("no atlas open", 400) });
		expect(await screen.findByText("The screenshots could not be listed: no atlas open")).toBeInTheDocument();
	});
});
