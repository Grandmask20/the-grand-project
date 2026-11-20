import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ModeBar } from "@/components/map/ModeBar";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("ModeBar", () => {
	afterEach(resetStore);

	it("is no line at all with nothing to say (the map keeps its height)", () => {
		const { container } = renderWithApp(<ModeBar />);
		expect(container).toBeEmptyDOMElement();
	});

	it("a map mode's line has End (user: only Esc ended one)", async () => {
		const { user } = renderWithApp(<ModeBar />);
		act(() => useAppStore.getState().setMode({ kind: "route-edit", id: 5 }));
		expect(screen.getByText(/Adjust route: click a map/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "End" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("says nothing of drawing while Biome select's menu is up", () => {
		renderWithApp(<ModeBar />);
		act(() => {
			useAppStore.getState().setMode({ kind: "lasso" });
			useAppStore.setState({ lassoAsked: true });
		});
		expect(screen.queryByText(/draw around the maps/)).toBeNull();
	});

	it("bookmarks hidden while the Saved tab is open: says so, and Show them switches them on", async () => {
		const hidden = {
			...state,
			settings: { ...state.settings, layers: { ...state.settings.layers, Bookmarks: false } },
		};
		const { user, calls } = renderWithApp(<ModeBar />, {
			"GET /api/state": hidden,
			"PATCH /api/settings": state.settings,
		});
		act(() => useAppStore.getState().setTab("find"));
		expect(screen.queryByText("Bookmarks are currently hidden")).toBeNull();
		act(() => useAppStore.getState().setTab("bookmarks"));
		await user.click(screen.getByRole("button", { name: "Show them" }));
		await waitFor(() => expect(calls.some((c) => c.path === "/api/settings")).toBe(true));
	});

	it("puts the error under the mode's line", () => {
		const { container } = renderWithApp(<ModeBar />);
		act(() => {
			useAppStore.getState().setMode({ kind: "route-edit", id: 5 });
			useAppStore.getState().showError("A route needs two maps: delete it instead.", true);
		});
		const lines = [...(container.firstElementChild as HTMLElement).children].map((c) => c.textContent ?? "");
		expect(lines[0]).toMatch(/Adjust route/);
		expect(lines[lines.length - 1]).toMatch(/A route needs two maps/);
	});
});
