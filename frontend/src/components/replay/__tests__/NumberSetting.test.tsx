import { act, render, screen, waitFor } from "@testing-library/react";
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

	it("a value still settling when the box is disabled (a recording started) is dropped (CodeRabbit)", async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn();
		const { rerender } = render(<NumberSetting label="length" value={30} lo={5} hi={600} onCommit={onCommit} />);
		const box = screen.getByRole("spinbutton", { name: "length" });
		await user.clear(box);
		await user.type(box, "45");
		rerender(<NumberSetting label="length" value={30} lo={5} hi={600} disabled onCommit={onCommit} />);
		await new Promise((r) => setTimeout(r, 800));
		expect(onCommit).not.toHaveBeenCalled();
		expect(box).toHaveValue(30);
	});

	it("refused, the box shows the setting again; typed on meanwhile, it keeps what's typed (CodeRabbit)", async () => {
		const user = userEvent.setup();
		let refuse: (ok: boolean) => void = () => {};
		const onCommit = vi.fn(
			() =>
				new Promise<boolean>((r) => {
					refuse = r;
				}),
		);
		render(<NumberSetting label="length" value={45} lo={5} hi={600} onCommit={onCommit} />);
		const box = screen.getByRole("spinbutton", { name: "length" });
		await user.clear(box);
		await user.type(box, "60{Enter}");
		expect(onCommit).toHaveBeenCalledWith(60);
		await act(async () => refuse(false));
		expect(box).toHaveValue(45);
		// a refusal that comes after newer typing leaves the box alone
		await user.clear(box);
		await user.type(box, "70{Enter}");
		await user.type(box, "5");
		await act(async () => refuse(false));
		expect(box).toHaveValue(705);
	});

	it("typed back to the setting while another value is on its way, that is sent too (CodeRabbit)", async () => {
		const user = userEvent.setup();
		const onCommit = vi.fn((_v: number) => new Promise<boolean>(() => {})); // (no answers yet)
		render(<NumberSetting label="length" value={30} lo={5} hi={600} onCommit={onCommit} />);
		const box = screen.getByRole("spinbutton", { name: "length" });
		await user.clear(box);
		await user.type(box, "60{Enter}");
		await user.clear(box);
		await user.type(box, "30{Enter}");
		expect(onCommit.mock.calls.map((c) => c[0])).toEqual([60, 30]);
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
