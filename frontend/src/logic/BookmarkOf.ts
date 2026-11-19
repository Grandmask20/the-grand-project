import type { Bookmarks } from "@/domain/bookmarks/Bookmarks";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import type { Point } from "@/logic/Geo";
import type { BookmarkEdit } from "@/store/AppStore";

/** The bookmark an item is, or the one on it (a bookmarked map): ready to edit, or null when it has none.
 *
 * A map's details carry the id of the bookmark on it; before, only a bookmark pin itself counted, so a bookmarked map
 * offered "Bookmark this…" again and made a second bookmark (user: "need an un-bookmark").
 *
 * @param info The item (a pick or a selection).
 * @param bookmarks The bookmark list (for a map's bookmark: its name, group and note).
 * @returns Its bookmark as an edit, or null.
 */
export function bookmarkOf(info: ItemInfo | null, bookmarks: Bookmarks | undefined): BookmarkEdit | null {
	if (!info || info.kind === "path") return null;
	if (info.kind === "bookmark")
		return {
			id: info.id,
			x: info.x,
			y: info.y,
			name: info.name ?? "",
			group: info.group ?? "Other",
			note: info.note ?? "",
		};
	if (info.bookmark == null) return null;
	// (the list not loaded yet: the id is enough to edit or remove it)
	if (!bookmarks) return { id: info.bookmark, x: info.x, y: info.y, name: info.title, group: "Other", note: "" };
	for (const g of bookmarks.groups) {
		const b = g.items.find((it) => it.id === info.bookmark);
		if (b) return { id: b.id, x: b.x, y: b.y, name: b.name, group: g.name, note: b.note };
	}
	return null; // removed: the map's details catch up a moment later
}

/** A new bookmark on an item (its place and suggested name), or on a spot of the map when nothing is there.
 *
 * @param hit What is at the spot, or null.
 * @param at The spot (atlas units).
 * @returns The new bookmark to edit.
 */
export function newBookmark(hit: ItemInfo | null, at: Point): BookmarkEdit {
	const on = hit && hit.kind !== "path";
	return {
		id: null,
		x: on ? hit.x : at[0],
		y: on ? hit.y : at[1],
		name: on ? (hit.suggest?.name ?? hit.title) : "",
		group: on ? (hit.suggest?.group ?? "Other") : "Other",
		note: "",
	};
}
