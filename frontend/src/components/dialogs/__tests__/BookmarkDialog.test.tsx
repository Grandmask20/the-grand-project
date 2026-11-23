import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BookmarkDialog } from "@/components/dialogs/BookmarkDialog";
import { useAppStore } from "@/store/AppStore";
import { bookmarks } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("BookmarkDialog", () => {
	it("adds a bookmark where it was asked for", async () => {
		const { user, calls } = renderWithApp(<BookmarkDialog />, {
			"GET /api/bookmarks": bookmarks,
			"POST /api/bookmarks": { id: 1 },
		});
		act(() =>
			useAppStore.getState().editBookmark({ id: null, x: 10, y: 20, name: "Breach", group: "Breach", note: "" }),
		);
		const name = await screen.findByLabelText("Name");
		await user.clear(name);
		await user.type(name, "my breach");
		await user.click(screen.getByRole("button", { name: "Save" }));
		await waitFor(() =>
			expect(calls.find((c) => c.method === "POST")?.body).toEqual({
				x: 10,
				y: 20,
				name: "my breach",
				group: "Breach",
				note: "",
				colour: "", // (a new one: none of its own, its group's)
				icon: "",
				plain: false,
			}),
		);
		await waitFor(() => expect(useAppStore.getState().bookmarkEdit).toBeNull());
	});

	it("needs a name", async () => {
		const { user } = renderWithApp(<BookmarkDialog />, { "GET /api/bookmarks": bookmarks });
		act(() => useAppStore.getState().editBookmark({ id: 0, x: 1, y: 1, name: "", group: "Other", note: "" }));
		await user.click(await screen.findByRole("button", { name: "Save" }));
		expect(screen.getByText("A bookmark needs a name.")).toBeInTheDocument();
	});
});
