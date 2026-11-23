import type { ItemInfo } from "@/domain/map/ItemInfo";
import type { Point } from "@/logic/Geo";
import type { BookmarkEdit } from "@/store/AppStore";

/** The bookmark an item is, or the one on it (a bookmarked map): ready to edit, or null when it has none.
 *
 * A map's details carry the bookmark on it, with its own name, group and note (`bookmark_of`); before, only a bookmark
 * pin itself counted, so a bookmarked map offered "Bookmark this…" again and made a second bookmark (user: "need an
 * un-bookmark"). They come with the details, not from the bookmark list: matched against the list, an edit could pair
 * the id with another moment's list, or guess the group and note before it loaded and save the guess (CodeRabbit).
 *
 * @param info The item (a pick or a selection).
 * @returns Its bookmark as an edit, or null.
 */
export function bookmarkOf(info: ItemInfo | null): BookmarkEdit | null {
	if (!info || info.kind === "path") return null;
	if (info.kind === "bookmark")
		return {
			id: info.id,
			x: info.x,
			y: info.y,
			name: info.name ?? "",
			group: info.group ?? "Other",
			note: info.note ?? "",
			colour: info.colour,
			icon: info.icon,
			plain: info.plain,
		};
	const b = info.bookmark_of;
	return b
		? {
				id: b.id,
				x: info.x,
				y: info.y,
				name: b.name,
				group: b.group,
				note: b.note,
				colour: b.colour,
				icon: b.icon,
				plain: b.plain,
			}
		: null;
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
