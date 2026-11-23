import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RouteProgress } from "@/components/route/RouteProgress";

describe("RouteProgress (a route tracked, as a card)", () => {
	it("shows its ends, its maps (each once), how many are left and how far along it is", () => {
		// a branch: 1 → 2 → 3, back through 2, on to 4 (2 counted once)
		render(<RouteProgress path={[1, 2, 3, 2, 4]} at={2} />);
		expect(screen.getByText("map #1 → map #4")).toBeInTheDocument();
		expect(screen.getByText(/4 maps · 1 left/)).toBeInTheDocument();
		expect(screen.getByRole("progressbar", { name: "How far along the route" })).toHaveAttribute("aria-valuenow", "67");
	});

	it("at its last map: no maps left, all the way along; bare inside a bookmark's row", () => {
		render(<RouteProgress path={[5, 6]} at={1} bare />);
		expect(screen.getByText("map #5 → map #6 · 2 maps · last map")).toBeInTheDocument();
		expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
	});
});
