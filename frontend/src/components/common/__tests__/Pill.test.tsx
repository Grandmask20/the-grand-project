import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Pill } from "@/components/common/Pill";

describe("Pill", () => {
	it("is a switch: pressed when on, and a click asks to change it", async () => {
		const onClick = vi.fn();
		render(
			<Pill on onClick={onClick}>
				Maps
			</Pill>,
		);
		expect(screen.getByRole("button", { name: "Maps" })).toHaveAttribute("aria-pressed", "true");
		await userEvent.click(screen.getByRole("button", { name: "Maps" }));
		expect(onClick).toHaveBeenCalled();
	});

	it("short words, its whole name for screen readers and the tooltip", () => {
		render(
			<Pill on={false} label="only what 2+ screenshots show" onClick={() => {}}>
				2+ screenshots
			</Pill>,
		);
		const pill = screen.getByRole("button", { name: "only what 2+ screenshots show" });
		expect(pill).toHaveTextContent("2+ screenshots");
		expect(pill).toHaveAttribute("title", "only what 2+ screenshots show");
		expect(pill).toHaveAttribute("aria-pressed", "false");
	});
});
