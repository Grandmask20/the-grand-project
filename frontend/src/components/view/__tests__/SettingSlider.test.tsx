import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { SettingSlider } from "@/components/view/SettingSlider";

/** The slider with its setting kept like the page's (a save changes the value it shows). */
function Saved({
	onCommit,
	onPreview,
	from = 20,
}: {
	onCommit: (v: number) => void;
	onPreview?: (v: number) => void;
	from?: number;
}) {
	const [v, setV] = useState(from);
	return (
		<SettingSlider
			label="drawn by at least"
			value={v}
			min={0}
			max={100}
			step={5}
			onCommit={(x) => {
				onCommit(x);
				setV(x);
			}}
			onPreview={onPreview}
			format={(x) => `${x}%`}
		/>
	);
}

describe("SettingSlider", () => {
	it("saves each arrow key step, a step back to the old value too", async () => {
		const onCommit = vi.fn();
		const onPreview = vi.fn();
		render(<Saved onCommit={onCommit} onPreview={onPreview} />);
		screen.getByRole("slider").focus();
		await userEvent.keyboard("{ArrowRight}");
		expect(onCommit).toHaveBeenLastCalledWith(25);
		expect(screen.getByText("25%")).toBeTruthy();
		// (a stale drag start from the step before skipped this one: CodeRabbit)
		await userEvent.keyboard("{ArrowLeft}");
		expect(onCommit).toHaveBeenLastCalledWith(20);
		expect(onCommit).toHaveBeenCalledTimes(2);
		expect(onPreview).not.toHaveBeenCalled(); // a key step is saved, not previewed
	});

	it("saves nothing when let go where it started", async () => {
		const onCommit = vi.fn();
		render(<SettingSlider label="size" value={0} min={0} max={8} step={1} onCommit={onCommit} />);
		screen.getByRole("slider").focus();
		await userEvent.keyboard("{ArrowLeft}"); // already at the minimum
		expect(onCommit).not.toHaveBeenCalled();
	});

	it("a drag cut short (the slider gone) takes its preview back", () => {
		const onPreview = vi.fn();
		const { unmount } = render(<Saved onCommit={vi.fn()} onPreview={onPreview} />);
		fireEvent.pointerDown(screen.getByRole("slider").closest("[data-slot=slider]") as Element);
		unmount();
		expect(onPreview).toHaveBeenLastCalledWith(20);
	});

	it("pressed and let go without moving: the drag ends, and nothing is taken back later", async () => {
		// (Radix reports no release when the value didn't change: the drag stayed open, and a later unmount took back
		// a preview that never was, over the saved settings: CodeRabbit)
		const onPreview = vi.fn();
		const onCommit = vi.fn();
		// at the minimum: the press lands where it is (jsdom's slider has no size), as a press without moving
		const { unmount } = render(<Saved onCommit={onCommit} onPreview={onPreview} from={0} />);
		const root = screen.getByRole("slider").closest("[data-slot=slider]") as Element;
		fireEvent.pointerDown(root);
		fireEvent.pointerUp(root);
		await Promise.resolve(); // (the drag ends just after the release)
		unmount();
		expect(onPreview).not.toHaveBeenCalled();
		expect(onCommit).not.toHaveBeenCalled();
	});
});
