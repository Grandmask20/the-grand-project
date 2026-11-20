import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { InspectorPanel } from "@/components/layout/InspectorPanel";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("InspectorPanel", () => {
	afterEach(resetStore);

	it("nothing selected: no panel (the map takes its room)", () => {
		const { container } = renderWithApp(<InspectorPanel />);
		expect(container).toBeEmptyDOMElement();
	});

	it("shows what is selected at the map's side, and closing it lets go of the selection", async () => {
		const { user } = renderWithApp(<InspectorPanel />, { "GET /api/info": nodeInfo });
		act(() => useAppStore.getState().select(nodeInfo));
		expect(screen.getByRole("complementary", { name: "Selected" })).toBeInTheDocument();
		expect(await screen.findByText("Map #12: Breach")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Close" }));
		expect(useAppStore.getState().selected).toBeNull();
		expect(screen.queryByRole("complementary")).toBeNull();
	});
});
