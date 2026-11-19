import { act, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBar } from "@/components/layout/StatusBar";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp } from "@/test/RenderWithApp";

describe("StatusBar", () => {
	it("shows the app's status, or what the mode wants", () => {
		renderWithApp(<StatusBar connected />);
		expect(screen.getByText("opened atlas.json")).toBeInTheDocument();
		act(() => useAppStore.getState().setMode({ kind: "lasso" }));
		expect(screen.getByText(/Draw around the maps of the biome/)).toBeInTheDocument();
	});

	it("says when the app can't be reached", () => {
		renderWithApp(<StatusBar connected={false} />);
		expect(screen.getByText("not connected to the app")).toBeInTheDocument();
	});
});
