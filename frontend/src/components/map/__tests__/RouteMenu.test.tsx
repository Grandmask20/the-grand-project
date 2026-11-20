import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RouteMenu } from "@/components/map/RouteMenu";

describe("RouteMenu", () => {
	it("answers once: picking Track now isn't followed by a Cancel when the menu closes", async () => {
		// (the second answer cleared the route that Track now had just started)
		const onChoose = vi.fn();
		render(<RouteMenu x={0} y={0} from={218} to={612} maps={20} onChoose={onChoose} />);
		expect(screen.getByText(/Map #218 → map #612: 20 maps/)).toBeInTheDocument();
		await userEvent.click(screen.getByRole("menuitem", { name: "Track now" }));
		expect(onChoose.mock.calls).toEqual([["track"]]);
	});
});
