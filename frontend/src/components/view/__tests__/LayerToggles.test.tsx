import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LayerToggles } from "@/components/view/LayerToggles";
import { renderWithApp } from "@/test/RenderWithApp";

describe("LayerToggles", () => {
	it("shows which layers are on (Doubtful and Removed start off)", () => {
		renderWithApp(<LayerToggles />);
		expect(screen.getByRole("button", { name: "Paths" })).toHaveAttribute("aria-pressed", "true");
		expect(screen.getByRole("button", { name: "Removed" })).toHaveAttribute("aria-pressed", "false");
		expect(screen.getByRole("button", { name: "3D models" })).toHaveAttribute("aria-pressed", "true");
	});

	it("Routes goes on -> saved only -> off (the route shown, and the saved ones)", async () => {
		const { user, calls } = renderWithApp(<LayerToggles />, { "PATCH /api/settings": (b: unknown) => b });
		await user.click(screen.getByRole("button", { name: "Routes: on" }));
		await user.click(await screen.findByRole("button", { name: "Routes: saved only" }));
		expect(await screen.findByRole("button", { name: "Routes: off" })).toHaveAttribute("aria-pressed", "false");
		await user.click(screen.getByRole("button", { name: "Routes: off" }));
		expect(await screen.findByRole("button", { name: "Routes: on" })).toHaveAttribute("aria-pressed", "true");
		await waitFor(() =>
			expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
				{ layers: { Route: false, "Saved routes": true } },
				{ layers: { Route: false, "Saved routes": false } },
				{ layers: { Route: true, "Saved routes": true } },
			]),
		);
	});

	it("switches a layer and saves it", async () => {
		const { user, calls } = renderWithApp(<LayerToggles />, { "PATCH /api/settings": (b: unknown) => b });
		await user.click(screen.getByRole("button", { name: "Paths" }));
		expect(screen.getByRole("button", { name: "Paths" })).toHaveAttribute("aria-pressed", "false"); // at once
		await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ layers: { Paths: false } }));
	});
});
