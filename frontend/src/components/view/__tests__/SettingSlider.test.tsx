import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SettingSlider } from "@/components/view/SettingSlider";

describe("SettingSlider", () => {
	it("shows each step and saves once when let go", async () => {
		const onCommit = vi.fn();
		const onPreview = vi.fn();
		render(
			<SettingSlider
				label="drawn by at least"
				value={20}
				min={0}
				max={100}
				step={5}
				onCommit={onCommit}
				onPreview={onPreview}
				format={(v) => `${v}%`}
			/>,
		);
		const thumb = screen.getByRole("slider");
		thumb.focus();
		await userEvent.keyboard("{ArrowRight}");
		expect(onPreview).toHaveBeenLastCalledWith(25);
		expect(onCommit).toHaveBeenCalledTimes(1);
		expect(onCommit).toHaveBeenCalledWith(25);
		expect(screen.getByText("25%")).toBeTruthy();
	});

	it("saves nothing when let go where it started", async () => {
		const onCommit = vi.fn();
		render(<SettingSlider label="size" value={0} min={0} max={8} step={1} onCommit={onCommit} />);
		screen.getByRole("slider").focus();
		await userEvent.keyboard("{ArrowLeft}"); // already at the minimum
		expect(onCommit).not.toHaveBeenCalled();
	});
});
