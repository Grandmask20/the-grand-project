import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Timeline } from "@/components/replay/Timeline";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import { meta } from "@/test/Fixtures";

const plan = {
	settings: meta.replay.defaults,
	n_steps: 4,
	step_session: [0, 0, 1, 1],
	ticks: [0, 2],
} as unknown as ReplayPlan;

describe("Timeline", () => {
	it("shows where the replay is", () => {
		render(<Timeline plan={plan} pos={2} sessions={["#f00", "#00f"]} onSeek={vi.fn()} />);
		expect(screen.getByRole("slider", { name: "Replay position" })).toHaveAttribute("aria-valuenow", "2");
	});

	it("seeks with the keys", () => {
		const onSeek = vi.fn();
		render(<Timeline plan={plan} pos={2} sessions={[]} onSeek={onSeek} />);
		fireEvent.keyDown(screen.getByRole("slider"), { key: "ArrowRight" });
		expect(onSeek.mock.calls[0][0]).toBeCloseTo(2.04);
	});
});
