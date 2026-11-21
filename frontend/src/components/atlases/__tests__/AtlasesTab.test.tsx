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

	it("re-checks an atlas from its card, another one opened first by the app (user: a refresh icon)", async () => {
		const { user, calls } = renderWithApp(<AtlasesTab />, {
			"GET /api/atlases": atlases,
			"POST /api/atlas/recheck-file": { ok: true },
		});
		const button = await screen.findByRole("button", { name: "Re-check second" });
		expect(button).toHaveAttribute("title", "Open and re-check this atlas");
		expect(screen.getByRole("button", { name: "Re-check default" })).toHaveAttribute("title", "Re-check this atlas");
		await user.click(button);
		expect(calls.some((c) => c.path === "/api/atlas/recheck-file")).toBe(false); // (asked first)
		const asked = useAppStore.getState().confirm;
		expect(asked?.title).toBe("Re-check atlas");
		expect(asked?.text).toMatch(/"second" is opened first/);
		asked?.onYes();
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/atlas/recheck-file")?.body).toEqual({
				path: "/atlases/two/atlas.json",
			}),
		);
		expect(calls.some((c) => c.path === "/api/atlas/open")).toBe(false); // (one request: the app opens it)
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
