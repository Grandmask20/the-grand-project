import { screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LogTab } from "@/components/log/LogTab";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const download = vi.hoisted(() => vi.fn());
vi.mock("@/utils/Download", () => ({ download }));

describe("LogTab", () => {
	beforeEach(() => download.mockClear());
	afterEach(resetStore);

	it("lists the app's log", () => {
		renderWithApp(<LogTab />, { "GET /api/state": { ...state, log: ["12:00:00  opened", "12:01:00  added 3"] } });
		expect(screen.getByText("12:00:00 opened")).toBeInTheDocument();
		expect(screen.getByText("12:01:00 added 3")).toBeInTheDocument();
	});

	it("saves the log as a text file", async () => {
		const { user } = renderWithApp(<LogTab />, { "GET /api/state": { ...state, log: ["a", "b"] } });
		await user.click(screen.getByRole("button", { name: "Save log" }));
		expect(download).toHaveBeenCalledWith("a\nb\n", "grand-project-log.txt");
	});

	it("the frame log is recorded when switched on, and can be saved", async () => {
		const { user } = renderWithApp(<LogTab />);
		expect(screen.queryByRole("button", { name: /Save frame log/ })).not.toBeInTheDocument();
		await user.click(screen.getByRole("switch", { name: "Frame log" }));
		expect(useAppStore.getState().frameLog).toBe(true);
		await user.click(screen.getByRole("button", { name: /Save frame log/ }));
		expect(download).toHaveBeenCalledWith(expect.any(String), "frame-log.csv", "text/csv");
	});
});
