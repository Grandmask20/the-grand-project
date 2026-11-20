import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { StatusBar } from "@/components/layout/StatusBar";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("StatusBar", () => {
	afterEach(resetStore);

	it("shows the app's status and the atlas's numbers (the mode's hint is the line above the map)", () => {
		renderWithApp(<StatusBar connected />);
		expect(screen.getByText("opened atlas.json")).toBeInTheDocument();
		expect(screen.getByText(/80 maps · 9 icons · 4 landmarks · 4\s+screenshots/)).toBeInTheDocument();
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		expect(screen.queryByText(/Biome select: draw around the maps/)).toBeNull();
	});

	it("says when the app can't be reached", () => {
		renderWithApp(<StatusBar connected={false} />);
		expect(screen.getByText("not connected to the app")).toBeInTheDocument();
	});

	it("holds the map's camera, its layers and the log's button", async () => {
		const { user } = renderWithApp(<StatusBar connected />);
		expect(screen.getByRole("group", { name: "Map view" })).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Layers" })).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Log" }));
		expect(useAppStore.getState().logOpen).toBe(true);
		expect(screen.getByRole("button", { name: "Log" })).toHaveAttribute("aria-expanded", "true");
		await user.click(screen.getByRole("button", { name: "Log" }));
		expect(useAppStore.getState().logOpen).toBe(false);
	});
});
