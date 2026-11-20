import type { ItemKind } from "@/domain/map/ItemKind";

export const AppQueryKeys = {
	state: ["state"] as const,
	parts: ["parts"] as const,
	meta: ["meta"] as const,
	atlases: ["atlases"] as const,
	types: ["types"] as const,
	search: (q: string) => ["search", q] as const,
	list: (type: string) => ["list", type] as const,
	info: (kind: ItemKind, id: number) => ["info", kind, id] as const,
	bookmarks: ["bookmarks"] as const,
	graph: ["graph"] as const,
	recent: ["recent"] as const,
	sources: (x: number, y: number) => ["sources", x, y] as const,
	fs: (path: string, files: boolean) => ["fs", path, files] as const,
	frames: ["frames"] as const,
	heat: (upto: number | undefined) => ["heat", upto ?? -1] as const,
	fog: ["fog"] as const,
	debug: ["debug"] as const,
	update: ["update"] as const,
	/** What changes when the atlas or its model changes. */
	model: [
		["types"],
		["search"],
		["list"],
		["info"],
		["graph"],
		["frames"],
		["heat"],
		["bookmarks"],
		["recent"],
	] as const,
};
