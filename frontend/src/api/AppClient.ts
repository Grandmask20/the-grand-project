import type { Ghost } from "@/domain/adding/Ghost";
import type { RecentOutline } from "@/domain/adding/RecentOutline";
import type { WatchState } from "@/domain/adding/WatchState";
import type { AppState } from "@/domain/app/AppState";
import type { Meta, ReplaySettings } from "@/domain/app/Meta";
import type { SettingsChange, UiSettings } from "@/domain/app/UiSettings";
import type { AtlasCard } from "@/domain/atlas/AtlasCard";
import type { AtlasSummary } from "@/domain/atlas/AtlasSummary";
import type { FolderOpened } from "@/domain/atlas/FolderOpened";
import type { FsListing } from "@/domain/atlas/FsListing";
import type { BookmarkDraft, Bookmarks } from "@/domain/bookmarks/Bookmarks";
import type { DebugMark, DebugMarkDraft, DebugMarks } from "@/domain/debug/DebugMarks";
import type { ResultRow, SearchResult } from "@/domain/find/SearchResult";
import type { SourceShot } from "@/domain/find/Sources";
import type { TypeList } from "@/domain/find/TypeList";
import type { Graph } from "@/domain/map/Graph";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import type { ItemKind, ItemRef } from "@/domain/map/ItemKind";
import type { MapInfo } from "@/domain/map/MapInfo";
import type { Frames } from "@/domain/replay/Frames";
import type { ReplayFog, ReplayPlan } from "@/domain/replay/ReplayPlan";
import type { Http } from "./Http";

type Ok = { ok: boolean };
type Point = [number, number];

export function createAppClient(http: Http) {
	return {
		// the app
		getState: () => http.get<AppState>("/api/state"),
		getMeta: () => http.get<Meta>("/api/meta"),
		getSettings: () => http.get<UiSettings>("/api/settings"),
		updateSettings: (change: SettingsChange) => http.send<UiSettings>("PATCH", "/api/settings", change),
		answer: (id: number, yes: boolean) => http.send<Ok>("POST", `/api/questions/${id}`, { yes }),
		quit: () => http.send<Ok>("POST", "/api/quit"),
		eventsUrl: () => http.url("/api/events"),

		// atlases
		getAtlases: () => http.get<AtlasCard[]>("/api/atlases"),
		thumbUrl: (json: string, v: number) => http.url("/api/atlases/thumb", { json, v }),
		renameAtlas: (json: string, name: string) => http.send<Ok>("POST", "/api/atlases/rename", { json, name }),
		forgetAtlas: (json: string) => http.send<Ok>("POST", "/api/atlases/forget", { json }),
		deleteAtlas: (json: string) => http.send<{ failed: string[] }>("POST", "/api/atlases/delete", { json }),
		openAtlas: (path: string) => http.send<AtlasSummary>("POST", "/api/atlas/open", { path }),
		newAtlas: (path: string) => http.send<AtlasSummary>("POST", "/api/atlas/new", { path }),
		openFolder: (folder: string) => http.send<FolderOpened>("POST", "/api/atlas/folder", { folder }),
		createFromFolder: (folder: string) => http.send<{ adding: number }>("POST", "/api/atlas/folder/create", { folder }),
		saveAtlas: () => http.send<Ok>("POST", "/api/atlas/save"),
		closeAtlas: () => http.send<Ok>("POST", "/api/atlas/close"),
		exportPngs: () => http.send<{ files: string[] }>("POST", "/api/atlas/export"),
		recheck: () => http.send<Ok>("POST", "/api/atlas/recheck"),
		fixSeams: () => http.send<Ok>("POST", "/api/seams"),
		stopSeams: () => http.send<Ok>("DELETE", "/api/seams"),
		listDir: (path: string, files = true) => http.get<FsListing>("/api/fs", { path, files: files ? 1 : 0 }),
		upload: (file: File) => http.upload<{ path: string }>("/api/upload", file, file.name),

		// adding screenshots
		addScreenshots: (paths: string[]) => http.send<{ queued: number }>("POST", "/api/screenshots", { paths }),
		ghost: (path: string) => http.send<Ghost>("POST", "/api/ghost", { path }),
		pictureUrl: (id: number) => http.url(`/api/pictures/${id}.png`),
		placeByHand: (path: string, x: number, y: number) => http.send<Ok>("POST", "/api/place", { path, x, y }),
		undo: () => http.send<{ names: string[] }>("POST", "/api/undo"),
		retryWaiting: (indices: number[] | null) =>
			http.send<{ retrying: number }>("POST", "/api/waiting/retry", { indices }),
		takeWaiting: (index: number) => http.send<{ path: string }>("POST", "/api/waiting/take", { index }),
		getRecent: () => http.get<RecentOutline[]>("/api/recent"),
		gotoRecent: (name: string) => http.send<{ centre: Point }>("POST", "/api/recent/goto", { name }),
		setWatch: (on: boolean) => http.send<WatchState>("POST", "/api/watch", { on }),
		setWatchFolder: (folder: string | null) => http.send<WatchState>("POST", "/api/watch/folder", { folder }),

		// the map
		getMap: () => http.get<MapInfo | null>("/api/map"),
		terrainTiles: (v: string) => `${absolute(http.url("/api/tiles/terrain/"))}{z}/{x}/{y}.jpg?v=${v}`,
		vectorTiles: (v: string, replay?: number) =>
			`${absolute(http.url("/api/tiles/vector/"))}{z}/{x}/{y}.pbf?v=${v}${replay ? `&r=${replay}` : ""}`,
		iconUrl: (name: string, size = 32) => http.url(`/api/icons/${encodeURIComponent(name)}.png`, { size }),
		// v: the pictures changed (the browser keeps them a year): bumped when they change
		spriteUrl: (name: string, style = "game art") =>
			http.url(`/api/icons/${encodeURIComponent(name)}.png`, { kind: "sprite", v: 2, style }),
		getGraph: () => http.get<Graph>("/api/graph"),
		pick: (x: number, y: number, z: number, layers?: Record<string, boolean>) =>
			http.send<ItemInfo | null>("POST", "/api/pick", { x, y, z, layers }),
		getInfo: (kind: ItemKind, id: number) => http.get<ItemInfo>("/api/info", { kind, id }),
		search: (q: string) => http.get<SearchResult>("/api/search", { q }),
		getTypes: () => http.get<TypeList>("/api/types"),
		listType: (type: string) => http.get<{ results: ResultRow[] }>("/api/list", { type }),
		getSources: (x: number, y: number) => http.get<SourceShot[]>("/api/sources", { x, y }),
		screenshotUrl: (name: string, w = 0) => http.url(`/api/screenshot/${encodeURIComponent(name)}`, { w }),

		// hand edits
		setLandmark: (x: number, y: number, kind: string, on: "landmark" | "map" = "landmark") =>
			http.send<Ok>("POST", "/api/landmark", { x, y, kind, on }),
		setCityType: (id: number, type: string | null) => http.send<Ok>("POST", "/api/city-type", { id, type }),
		lassoCount: (polygon: Point[]) => http.send<{ maps: number }>("POST", "/api/lasso", { polygon }),
		setBiome: (polygon: Point[], biome: string) =>
			http.send<{ maps: number }>("POST", "/api/biome", { polygon, biome }),

		// bookmarks
		getBookmarks: () => http.get<Bookmarks>("/api/bookmarks"),
		addBookmark: (b: BookmarkDraft) => http.send<{ id: number }>("POST", "/api/bookmarks", b),
		editBookmark: (id: number, b: Omit<BookmarkDraft, "x" | "y">) => http.send<Ok>("PATCH", `/api/bookmarks/${id}`, b),
		deleteBookmarks: (ids: number[]) => http.send<{ deleted: string[] }>("POST", "/api/bookmarks/delete", { ids }),
		moveBookmarks: (ids: number[], group: string) => http.send<Ok>("POST", "/api/bookmarks/move", { ids, group }),
		toggleBookmark: (id: number) => http.send<Ok>("POST", "/api/bookmarks/toggle", { id }),
		bookmarkAll: (items: ItemRef[], group: string) =>
			http.send<{ added: number; skipped: number }>("POST", "/api/bookmarks/all", { items, group }),
		newGroup: (name: string) => http.send<Ok>("POST", "/api/groups", { name }),
		renameGroup: (old: string, name: string) => http.send<Ok>("POST", "/api/groups/rename", { old, new: name }),
		toggleGroup: (name: string) => http.send<Ok>("POST", "/api/groups/toggle", { name }),

		// debug marks
		getDebug: () => http.get<DebugMarks>("/api/debug"),
		addDebugMark: (m: DebugMarkDraft) => http.send<DebugMark>("POST", "/api/debug", m),
		deleteDebugMark: (id: number) => http.send<Ok>("DELETE", `/api/debug/${id}`),
		clearDebugMarks: () => http.send<{ backup: string }>("POST", "/api/debug/clear"),

		// colour by and the replay
		getFrames: () => http.get<Frames>("/api/frames"),
		getHeat: (upto?: number) => http.get<{ box: [number, number, number, number] } | null>("/api/heat", { upto }),
		heatUrl: (upto?: number, v = 0) => http.url("/api/heat.png", { upto, v }),
		/** Where the map image shows ground on a grid (1 byte per cell, 1 = ground; "Colour by" tints only there). */
		groundMask: async (q: { x0: number; y0: number; cell: number; w: number; h: number }) => {
			const res = await fetch(http.url("/api/ground", q));
			return res.status === 200 ? new Uint8Array(await res.arrayBuffer()) : null;
		},
		openReplay: () => http.send<ReplayPlan>("POST", "/api/replay/open"),
		closeReplay: () => http.send<Ok>("POST", "/api/replay/close"),
		setReplay: (change: Partial<ReplaySettings>) => http.send<ReplayPlan>("PATCH", "/api/replay", change),
		getFog: () => http.get<ReplayFog>("/api/replay/fog"),
	};
}

/** MapLibre fetches tiles in a worker: their URLs must be absolute. */
function absolute(url: string): string {
	return new URL(url, window.location.href).href;
}

export type AppClient = ReturnType<typeof createAppClient>;
