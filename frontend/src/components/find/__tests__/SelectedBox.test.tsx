import { act, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SelectedBox } from "@/components/find/SelectedBox";
import { useAppStore } from "@/store/AppStore";
import { nodeInfo } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("SelectedBox", () => {
	it("asks for a click when nothing is selected", () => {
		renderWithApp(<SelectedBox />);
		expect(screen.getByText("Click a map, icon, landmark or bookmark.")).toBeInTheDocument();
	});

	it("shows a map's details and bookmarks it with the suggested name", async () => {
		const { user } = renderWithApp(<SelectedBox />, { "GET /api/info": nodeInfo });
		act(() => useAppStore.getState().select(nodeInfo));
		expect(await screen.findByText("Map #12: Breach")).toBeInTheDocument();
		expect(screen.getByText("position 440, 200")).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Bookmark" }));
		expect(useAppStore.getState().bookmarkEdit).toEqual({ id: null, x: 440, y: 200, name: "Breach", group: "Breach", note: "" });
		await user.click(screen.getByRole("button", { name: "Screenshots" }));
		expect(useAppStore.getState().sources).toEqual([440, 200]);
	});
});
