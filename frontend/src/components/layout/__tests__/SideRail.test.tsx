import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SideRail } from "@/components/layout/SideRail";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("SideRail", () => {
	afterEach(resetStore);

	it("lists Find, View, Saved and Atlases (the log is under the map now)", () => {
		renderWithApp(<SideRail side="left" />);
		expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Find", "View", "Saved", "Atlases"]);
		expect(screen.getByRole("tab", { name: "Find" })).toHaveAttribute("aria-selected", "true");
	});

	it("a tab opens the drawer on it; the open one clicked again folds the drawer away, and opens it again", async () => {
		const { user } = renderWithApp(<SideRail side="left" />);
		await user.click(screen.getByRole("tab", { name: "Saved" }));
		expect(useAppStore.getState()).toMatchObject({ tab: "bookmarks", panelOpen: true });
		await user.click(screen.getByRole("tab", { name: "Saved" }));
		expect(useAppStore.getState().panelOpen).toBe(false);
		expect(screen.getByRole("tab", { name: "Saved" })).toHaveAttribute("aria-selected", "false");
		await user.click(screen.getByRole("tab", { name: "Saved" }));
		expect(useAppStore.getState().panelOpen).toBe(true);
	});

	it("the arrow keys move to the next tab and open it", () => {
		renderWithApp(<SideRail side="right" />);
		fireEvent.keyDown(screen.getByRole("tab", { name: "Find" }), { key: "ArrowDown" });
		expect(useAppStore.getState().tab).toBe("view");
		expect(screen.getByRole("tab", { name: "View" })).toHaveFocus();
		fireEvent.keyDown(screen.getByRole("tab", { name: "View" }), { key: "ArrowUp" });
		fireEvent.keyDown(screen.getByRole("tab", { name: "Find" }), { key: "ArrowUp" });
		expect(useAppStore.getState().tab).toBe("atlases"); // (round the end)
	});
});
