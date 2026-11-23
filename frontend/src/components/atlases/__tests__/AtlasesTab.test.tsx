import { fireEvent, screen, waitFor } from "@testing-library/react";
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

	it("a card's buttons show only while it is pointed at or reached by the keyboard (user: reveal on hover)", async () => {
		renderWithApp(<AtlasesTab />, { "GET /api/atlases": atlases });
		const buttons = (await screen.findByRole("button", { name: "Rename second" })).parentElement;
		// (the column, not each button: a disabled button's own half opacity would show it)
		// (hidden only where hover works: a touch screen shows them, CodeRabbit)
		expect(buttons).toHaveClass(
			"can-hover:opacity-0",
			"group-hover/card:opacity-100",
			"group-has-[:focus-visible]/card:opacity-100",
		);
		expect(buttons?.closest(".group\\/card")).not.toBeNull();
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

	it("asks before re-checking an atlas from its card (user: a refresh icon, a prompt)", async () => {
		const { user, calls } = renderWithApp(<AtlasesTab />, { "GET /api/atlases": atlases });
		await user.click(await screen.findByRole("button", { name: "Re-check second" }));
		expect(useAppStore.getState().recheckAtlas).toBe("/atlases/two/atlas.json");
		expect(calls.some((c) => c.path.startsWith("/api/atlas/recheck"))).toBe(false); // (asked first)
	});

	it("asks what to do before deleting", async () => {
		const { user } = renderWithApp(<AtlasesTab />, { "GET /api/atlases": atlases });
		await user.click(await screen.findByRole("button", { name: "Delete second" }));
		expect(useAppStore.getState().deleteAtlas).toBe("/atlases/two/atlas.json");
	});

	it("right-click a card: open its folder (user: right click to open the atlas folder)", async () => {
		const { user, calls } = renderWithApp(<AtlasesTab />, {
			"GET /api/atlases": atlases,
			"POST /api/atlases/show-folder": { ok: true },
		});
		fireEvent.contextMenu(await screen.findByText("second"));
		await user.click(await screen.findByRole("menuitem", { name: "Open atlas folder" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/atlases/show-folder")?.body).toEqual({
				json: "/atlases/two/atlas.json",
			}),
		);
	});
});
