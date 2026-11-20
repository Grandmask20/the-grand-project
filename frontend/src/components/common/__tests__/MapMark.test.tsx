import { afterEach, describe, expect, it } from "vitest";
import { MapMark } from "@/components/common/MapMark";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const withStyle = (style: Record<string, unknown>) => ({
	"GET /api/state": { ...state, settings: { ...state.settings, style: { ...state.settings.style, ...style } } },
});

describe("MapMark", () => {
	afterEach(resetStore);

	it("circles: a circle in the map colour (the status colour while none is picked)", () => {
		const { container } = renderWithApp(<MapMark />);
		expect(container.querySelector("circle")).toHaveAttribute("fill", "#28dcff");
	});

	it("the colour picked, and squares", () => {
		const { container } = renderWithApp(<MapMark />, withStyle({ map_style: "squares", map_col: "#ff0000" }));
		expect(container.querySelector("rect")).toHaveAttribute("fill", "#ff0000");
		expect(container.querySelector("circle")).toBeNull();
	});

	it("bordered: the border in the map colour (or its own), the no-icon colour inside", () => {
		const { container } = renderWithApp(
			<MapMark />,
			withStyle({ map_fill: "bordered", map_col: "#ff0000", map_border: "#00ff00" }),
		);
		const c = container.querySelector("circle");
		expect(c).toHaveAttribute("stroke", "#00ff00");
		expect(c).toHaveAttribute("fill", "#1b1e24");
	});

	it("map icons, or hidden maps: the map art", () => {
		for (const map_style of ["map icons", "hidden"]) {
			const { container, unmount } = renderWithApp(<MapMark size={30} />, withStyle({ map_style }));
			expect(container.querySelector("img")).toHaveAttribute("width", "30");
			unmount();
		}
	});
});
