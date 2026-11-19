import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AtlasesTab } from "@/components/atlases/AtlasesTab";
import { useAppStore } from "@/store/AppStore";
import { atlases } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("AtlasesTab", () => {
	it("shows a card per atlas with its numbers", async () => {
		renderWithApp(<AtlasesTab />, { "GET /api/atlases": atlases });
		expect(await screen.findByText("80 maps · 9 icons · 4 screenshots")).toBeInTheDocument();
		expect(screen.getByText("reading…")).toBeInTheDocument();
		expect(screen.getByText("open")).toBeInTheDocument();
	});

	it("opens another atlas from its card", async () => {
		const { user, calls } = renderWithApp(<AtlasesTab />, {
			"GET /api/atlases": atlases,
			"POST /api/atlas/open": { name: "second" },
		});
		await user.click(await screen.findByText("second"));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/atlas/open")?.body).toEqual({ path: "/atlases/two/atlas.json" }),
		);
	});

	it("asks what to do before deleting", async () => {
		const { user } = renderWithApp(<AtlasesTab />, { "GET /api/atlases": atlases });
		await user.click(await screen.findByRole("button", { name: "Delete second" }));
		expect(useAppStore.getState().deleteAtlas).toBe("/atlases/two/atlas.json");
	});
});
