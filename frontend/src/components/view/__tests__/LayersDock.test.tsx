import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LayersDock } from "@/components/view/LayersDock";
import { nodeStates, state } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

/** The state with the dock opened (it remembers that in the settings). */
const opened = { ...state, settings: { ...state.settings, ui: { layers_open: true } } };

describe("LayersDock", () => {
	it("folded, shows no legend", () => {
		renderWithApp(<LayersDock />);
		expect(screen.getByRole("button", { name: "Layers" })).toHaveAttribute("aria-expanded", "false");
		expect(screen.queryByText("map: green")).toBeNull();
	});

	it("lists each map node state's colour in the legend", () => {
		renderWithApp(<LayersDock />, { "GET /api/state": opened });
		for (const [st, colour] of Object.entries(nodeStates)) {
			const swatch = screen.getByText(`map: ${st}`).querySelector("span");
			expect(swatch).toHaveStyle({ background: colour });
		}
		// the maps no screenshot named the state of keep their status colours
		expect(screen.getByText("map: 1 shot")).toBeInTheDocument();
	});
});
