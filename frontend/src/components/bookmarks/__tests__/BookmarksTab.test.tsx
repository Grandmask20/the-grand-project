import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { useAppStore } from "@/store/AppStore";
import { bookmarks } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("BookmarksTab", () => {
	it("lists the bookmarks by group", async () => {
		renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		expect(await screen.findByText("big boss")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Show Farm" })).toBeInTheDocument(); // a hidden group
	});

	it("hides a bookmark with its eye", async () => {
		const { user, calls } = renderWithApp(<BookmarksTab />, {
			"GET /api/bookmarks": bookmarks,
			"POST /api/bookmarks/toggle": { ok: true },
		});
		await user.click(await screen.findByRole("button", { name: "Hide big boss" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/bookmarks/toggle")?.body).toEqual({ id: 0 }));
	});

	it("deletes the picked bookmarks after asking", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
		await user.click(await screen.findByRole("checkbox", { name: "Pick big boss" }));
		await user.click(screen.getByRole("button", { name: "Delete" }));
		expect(useAppStore.getState().confirm?.text).toBe("Delete 1 bookmark?");
	});

	it("Add bookmark waits for a click on the map", async () => {
		const { user } = renderWithApp(<BookmarksTab />, { "GET /api/bookmarks": bookmarks });
		await user.click(screen.getByRole("button", { name: "Add bookmark" }));
		expect(useAppStore.getState().mode).toEqual({ kind: "bookmark" });
		expect(screen.getByText(/Click on the map where the bookmark goes/)).toBeInTheDocument();
	});
});
