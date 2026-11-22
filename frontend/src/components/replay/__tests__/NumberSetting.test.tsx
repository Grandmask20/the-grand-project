import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NumberSetting } from "@/components/replay/ReplayPanel";

describe("NumberSetting (the timelapse's length, maps per step)", () => {
	it("Enter uses what was typed at once, kept within its range (user: only leaving the box did)", async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		render(<NumberSetting label="length" value={30} lo={5} hi={600} onCommit={onCommit} />);
		const box = screen.getByRole("spinbutton", { name: "length" });
		await user.clear(box);
		await user.type(box, "900{Enter}");
		expect(onCommit).toHaveBeenCalledWith(600);
		expect(box).toHaveValue(600);
	});

	it("typing alone is used once it settles; a whole number where one is needed", async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		render(<NumberSetting label="per step" value={2} lo={1} hi={50} whole onCommit={onCommit} />);
		const box = screen.getByRole("spinbutton", { name: "per step" });
		await user.clear(box);
		await user.type(box, "7.6");
		expect(onCommit).not.toHaveBeenCalled();
		await waitFor(() => expect(onCommit).toHaveBeenCalledWith(8), { timeout: 1500 });
	});

	it("a pause mid-typing leaves a number out of range as typed (self review: it was set to the lowest)", async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		render(<NumberSetting label="length" value={30} lo={5} hi={600} onCommit={onCommit} />);
		const box = screen.getByRole("spinbutton", { name: "length" });
		await user.clear(box);
		await user.type(box, "2");
		await new Promise((r) => setTimeout(r, 800));
		expect(onCommit).not.toHaveBeenCalled();
		expect(box).toHaveValue(2);
		await user.type(box, "0");
		await waitFor(() => expect(onCommit).toHaveBeenCalledWith(20), { timeout: 1500 });
		expect(box).toHaveValue(20);
	});

	it("an empty box goes back to the setting, and the app's own changes show", async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		const { rerender } = render(<NumberSetting label="length" value={30} lo={5} hi={600} onCommit={onCommit} />);
		const box = screen.getByRole("spinbutton", { name: "length" });
		await user.clear(box);
		await user.tab();
		expect(box).toHaveValue(30);
		expect(onCommit).not.toHaveBeenCalled();
		rerender(<NumberSetting label="length" value={45} lo={5} hi={600} onCommit={onCommit} />);
		expect(box).toHaveValue(45);
	});
});
