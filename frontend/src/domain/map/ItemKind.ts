export type ItemKind = "node" | "path" | "landmark" | "icon" | "bookmark";

/** An item of the atlas: its kind and index in the app's lists. */
export interface ItemRef {
	kind: ItemKind;
	id: number;
}
