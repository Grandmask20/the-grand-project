import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProgressBox } from "@/components/common/ProgressBox";

describe("ProgressBox", () => {
	afterEach(() => vi.useRealTimers());

	it("shows nothing when idle", () => {
		render(<ProgressBox text={null} />);
		expect(screen.queryByRole("status")).not.toBeInTheDocument();
	});

	it("shows what is being done with moving dots and the seconds taken", () => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date(2026, 0, 1, 12, 0, 0));
		const { rerender } = render(<ProgressBox text="adding screenshots…" />);
		expect(screen.getByRole("status")).toHaveTextContent(/^adding screenshots\.+ 0s$/);
		act(() => vi.advanceTimersByTime(3_000));
		expect(screen.getByRole("status")).toHaveTextContent(/^adding screenshots\.+ 3s$/);
		rerender(<ProgressBox text={null} />);
		expect(screen.queryByRole("status")).not.toBeInTheDocument();
		rerender(<ProgressBox text="saving" />);
		expect(screen.getByRole("status")).toHaveTextContent(/ 0s$/); // a new job counts from 0
	});
});
