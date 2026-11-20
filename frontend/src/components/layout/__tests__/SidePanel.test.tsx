import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { SidePanel } from "@/components/layout/SidePanel";
import { useAppStore } from "@/store/AppStore";
import { atlases, bookmarks, state, types } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const app = {
	"GET /api/types": types,
	"GET /api/bookmarks": bookmarks,
	"GET /api/atlases": atlases,
	"PATCH /api/settings": state.settings,
};

describe("SidePanel", () => {
	beforeAll(() => {
		Element.prototype.scrollTo = () => {}; // (not in jsdom)
	});
	afterEach(resetStore);

	it("shows the rail and the drawer of the tab open, named after it", () => {
		renderWithApp(<SidePanel />, app);
		expect(screen.getByRole("tablist", { name: "Side panel" })).toBeInTheDocument();
		expect(screen.getByRole("heading", { name: "Find" })).toBeInTheDocument();
		expect(screen.getByRole("textbox", { name: "Find" })).toBeInTheDocument();
	});

	it("Saved holds the bookmarks and the route; Atlases the saved atlases and Auto-add", async () => {
		const { user } = renderWithApp(<SidePanel />, app);
		await user.click(screen.getByRole("tab", { name: "Saved" }));
		expect(screen.getByRole("heading", { name: "Saved" })).toBeInTheDocument();
		expect(screen.getByRole("tab", { name: "Bookmarks" })).toBeInTheDocument();
		expect(screen.getByRole("tab", { name: "Route" })).toBeInTheDocument();
		await user.click(screen.getByRole("tab", { name: "Atlases" }));
		expect(screen.getByRole("tab", { name: "Auto-add" })).toBeInTheDocument();
	});

	it("its close button folds the drawer away; the rail stays", async () => {
		const { user } = renderWithApp(<SidePanel />, app);
		await user.click(screen.getByRole("button", { name: "Close the panel" }));
		expect(useAppStore.getState().panelOpen).toBe(false);
		expect(screen.queryByRole("heading", { name: "Find" })).toBeNull();
		expect(screen.getByRole("tablist", { name: "Side panel" })).toBeInTheDocument();
	});

	it("the drawer's edge resizes it and saves the width; a double-click puts it back", async () => {
		const { calls } = renderWithApp(<SidePanel />, app);
		const edge = document.querySelector(".cursor-col-resize") as HTMLElement;
		edge.setPointerCapture = () => {};
		fireEvent.pointerDown(edge, { clientX: 100, pointerId: 1 });
		fireEvent.pointerMove(edge, { clientX: 160, pointerId: 1 });
		fireEvent.pointerUp(edge, { clientX: 160, pointerId: 1 });
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/settings")?.body).toEqual({ ui: { side_width: 460 } }),
		);
		fireEvent.doubleClick(edge);
		await waitFor(() =>
			expect(calls.filter((c) => c.path === "/api/settings").at(-1)?.body).toEqual({ ui: { side_width: 400 } }),
		);
	});
});
