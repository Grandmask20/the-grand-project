import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SideReveal } from "@/components/layout/SideReveal";
import { state } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("SideReveal", () => {
	it("hides the side panel, remembered as a setting (user's notes: a hideable sidebar)", async () => {
		const { user, calls } = renderWithApp(<SideReveal />, { "PATCH /api/settings": (b: unknown) => b });
		await user.click(screen.getByRole("button", { name: "Hide the side panel" }));
		await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ ui: { side_hidden: true } }));
	});

	it("hidden, it shows the panel again", async () => {
		const hidden = { ...state, settings: { ...state.settings, ui: { ...state.settings.ui, side_hidden: true } } };
		const { user, calls } = renderWithApp(<SideReveal />, {
			"GET /api/state": hidden,
			"PATCH /api/settings": (b: unknown) => b,
		});
		await user.click(screen.getByRole("button", { name: "Show the side panel" }));
		await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ ui: { side_hidden: false } }));
	});
});
