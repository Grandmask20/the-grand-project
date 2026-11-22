import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { LookMark, LookPicker } from "@/components/bookmarks/LookPicker";
import { BookmarkDialog } from "@/components/dialogs/BookmarkDialog";
import { GroupDialog } from "@/components/dialogs/GroupDialog";
import { isSymbol, symbolImageId } from "@/logic/Symbols";
import { useAppStore } from "@/store/AppStore";
import { bookmarks, types } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const userClick = (el: HTMLElement) => act(() => void fireEvent.click(el));

/** A bookmark's and a group's look (user: the pen opens a menu for icons and colours, per group and per bookmark). */
describe("looks", () => {
	afterEach(resetStore);

	it("the picker offers no look of its own, colours, and the atlas's icons", async () => {
		const picked: string[] = [];
		const { user } = renderWithApp(
			<LookPicker
				colour=""
				icon=""
				plain={false}
				onColour={(c) => picked.push(`colour ${c}`)}
				onIcon={(i) => picked.push(`icon ${i}`)}
				onPlain={(p) => picked.push(`plain ${p}`)}
				fallback={{ colour: "#c8a45c", from: "the group's" }}
			/>,
			{ "GET /api/types": types },
		);
		expect(screen.getByRole("button", { name: "No colour of its own (the group's)" })).toHaveAttribute(
			"aria-pressed",
			"true",
		);
		await user.click(screen.getByRole("button", { name: "#ef4444" }));
		await user.click(await screen.findByRole("button", { name: "Breach" }));
		await user.click(screen.getByRole("button", { name: "triangle" })); // a plain symbol (user: "utf icons")
		expect(picked).toEqual(["colour #ef4444", "plain false", "icon Breach", "icon sym:triangle"]);
	});

	it("a bookmark's pen: its look sent with the edit, and kept when the edit didn't know it", async () => {
		const { user, calls } = renderWithApp(<BookmarkDialog />, {
			"GET /api/bookmarks": bookmarks,
			"GET /api/types": types,
			"PATCH /api/bookmarks/0": { ok: true },
		});
		act(() =>
			useAppStore
				.getState()
				.editBookmark({ id: 0, x: 1, y: 1, name: "big boss", group: "Boss", note: "", colour: "", icon: "" }),
		);
		await user.click(await screen.findByRole("button", { name: "#4ade80" }));
		await user.click(screen.getByRole("button", { name: "Save" }));
		await waitFor(() =>
			expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
				name: "big boss",
				group: "Boss",
				note: "",
				colour: "#4ade80",
				icon: "",
				plain: false,
			}),
		);
		// an edit made without its look (none came with it): the app keeps the one it has
		calls.length = 0;
		act(() => useAppStore.getState().editBookmark({ id: 0, x: 1, y: 1, name: "big boss", group: "Boss", note: "" }));
		await user.click(await screen.findByRole("button", { name: "Save" }));
		await waitFor(() =>
			expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "big boss", group: "Boss", note: "" }),
		);
	});

	it("a group's pen opens its name and look; a rename and a look are both sent", async () => {
		const { user, calls } = renderWithApp(
			<>
				<BookmarksTab />
				<GroupDialog />
			</>,
			{
				"GET /api/bookmarks": bookmarks,
				"GET /api/types": types,
				"POST /api/groups/rename": { ok: true },
				"POST /api/groups/look": { ok: true },
			},
		);
		await user.click(await screen.findByRole("button", { name: "Edit Boss" }));
		expect(useAppStore.getState().groupEdit).toMatchObject({ name: "Boss", colour: "", icon: "", plain: false });
		const name = await screen.findByLabelText("Name");
		await user.clear(name);
		await user.type(name, "Bosses");
		await user.click(screen.getByRole("button", { name: "#a78bfa" }));
		await user.click(screen.getByRole("button", { name: "Save" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/groups/look")?.body).toBeDefined());
		expect(calls.find((c) => c.path === "/api/groups/rename")?.body).toEqual({ old: "Boss", new: "Bosses" });
		expect(calls.find((c) => c.path === "/api/groups/look")?.body).toEqual({
			name: "Bosses",
			colour: "#a78bfa",
			icon: "",
			plain: false,
		});
		await waitFor(() => expect(useAppStore.getState().groupEdit).toBeNull());
	});

	it("an atlas switch closes a group's dialog with the rest (resetAtlas)", () => {
		useAppStore.getState().editGroup({ name: "Boss", colour: "", icon: "", plain: false });
		useAppStore.getState().resetAtlas();
		expect(useAppStore.getState().groupEdit).toBeNull();
	});

	it("the colour none: an icon without its ring (user); a colour picked brings the ring back", async () => {
		const got: string[] = [];
		renderWithApp(
			<LookPicker
				colour="#ff0000"
				icon="Breach"
				plain={false}
				onColour={(c) => got.push(`colour ${c}`)}
				onIcon={() => {}}
				onPlain={(p) => got.push(`plain ${p}`)}
				fallback={{ colour: "#c8a45c", from: "standard" }}
			/>,
			{ "GET /api/types": types },
		);
		await userClick(screen.getByRole("button", { name: "No colour" }));
		await userClick(screen.getByRole("button", { name: "#60a5fa" }));
		expect(got).toEqual(["colour ", "plain true", "colour #60a5fa", "plain false"]);
		expect(screen.queryByText("Border")).not.toBeInTheDocument(); // (no border toggle any more)
	});

	it("marks: a symbol in its colour, a picture in a ring unless without one", () => {
		const { container, rerender } = renderWithApp(<LookMark colour="#ff0000" icon="sym:triangle" />);
		expect(container.querySelector("path")?.getAttribute("fill")).toBe("#ff0000");
		rerender(<LookMark colour="#ff0000" icon="Breach" />);
		expect((container.firstChild as HTMLElement).style.boxShadow).toContain("#ff0000");
		rerender(<LookMark colour="#ff0000" icon="Breach" plain />);
		expect((container.firstChild as HTMLElement).style.boxShadow).toBe("");
	});

	it("symbols are named sym:<name>, and the map draws each in its colour", () => {
		expect(isSymbol("sym:triangle") && !isSymbol("Breach") && !isSymbol("sym:nothing")).toBe(true);
		expect(symbolImageId("sym:star", "#00ff00")).toBe("sym:star:#00ff00");
	});
});
