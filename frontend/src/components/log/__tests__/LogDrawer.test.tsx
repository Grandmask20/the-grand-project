import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LogDrawer } from "@/components/log/LogDrawer";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const marks = { file: "debug_marks.json", marks: [] };

describe("LogDrawer", () => {
	afterEach(resetStore);

	it("closed: takes no room", () => {
		const { container } = renderWithApp(<LogDrawer />);
		expect(container).toBeEmptyDOMElement();
	});

	it("open: the log, and its close button folds it away", async () => {
		const { user } = renderWithApp(<LogDrawer />);
		act(() => useAppStore.getState().setLogOpen(true));
		expect(screen.getByRole("button", { name: "Save log" })).toBeInTheDocument();
		expect(screen.queryByRole("tab", { name: "Debug" })).toBeNull(); // (debug mode only)
		await user.click(screen.getByRole("button", { name: "Close the log" }));
		expect(useAppStore.getState().logOpen).toBe(false);
	});

	it("in debug mode it has the Debug page, opened by the app's old tab id", async () => {
		renderWithApp(<LogDrawer />, { "GET /api/state": { ...state, debug: true }, "GET /api/debug": marks });
		act(() => useAppStore.getState().setTab("debug"));
		expect(screen.getByRole("tab", { name: "Debug" })).toHaveAttribute("aria-selected", "true");
		expect(await screen.findByText(/Right-click a map, a path or an empty spot/)).toBeInTheDocument();
	});
});
