import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBanner } from "@/components/common/ErrorBanner";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

describe("ErrorBanner", () => {
	afterEach(() => {
		vi.useRealTimers();
		resetStore();
	});

	it("shows nothing without an error", () => {
		render(<ErrorBanner />);
		expect(screen.queryByRole("alert")).not.toBeInTheDocument();
	});

	it("shows the error until closed", async () => {
		useAppStore.getState().showError(new Error("the atlas could not be saved"));
		render(<ErrorBanner />);
		expect(screen.getByRole("alert")).toHaveTextContent("the atlas could not be saved");
		await userEvent.click(screen.getByRole("button", { name: "Close" }));
		expect(screen.queryByRole("alert")).not.toBeInTheDocument();
	});

	it("goes away by itself after 12 s", () => {
		vi.useFakeTimers();
		useAppStore.getState().showError("no space left");
		render(<ErrorBanner />);
		act(() => vi.advanceTimersByTime(11_000));
		expect(screen.getByRole("alert")).toBeInTheDocument();
		act(() => vi.advanceTimersByTime(1_500));
		expect(screen.queryByRole("alert")).not.toBeInTheDocument();
	});
});
