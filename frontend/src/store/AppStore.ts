import type { Map as MapLibreMap } from "maplibre-gl";
import { create } from "zustand";
import { useShallow } from "zustand/shallow";
import { isStale } from "@/api/Http";
import type { Ghost } from "@/domain/adding/Ghost";
import type { ResultRow } from "@/domain/find/SearchResult";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import type { Point } from "@/logic/Geo";

/** What a click on the map does. */
export type MapMode =
	| { kind: "normal" }
	| { kind: "lasso" }
	| { kind: "bookmark" }
	| { kind: "player" }
	| { kind: "ghost"; ghost: Ghost; centre: Point }
	| { kind: "debug-link"; from: number; note: string };

export type FilePick = {
	title: string;
	folders: boolean; // pick a folder (else files)
	multiple?: boolean;
	save?: string; // a file name to save as (new atlas): the folder is picked, the name typed
	start?: string;
	onPick: (paths: string[]) => void;
};

export type Prompt = {
	title: string;
	label: string;
	value: string;
	options?: string[];
	onOk: (value: string) => void;
};

export type Confirm = {
	title: string;
	text: string;
	yes: string;
	danger?: boolean;
	onYes: () => void;
};

export type BookmarkEdit = { id: number | null; x: number; y: number; name: string; group: string; note: string };

export type Camera = { x: number; y: number; px: number; bearing: number; pitch: number };

export interface ReplayUi {
	plan: ReplayPlan;
	pos: number;
	playing: boolean;
	recording: boolean;
}

export interface AppStoreState {
	map: MapLibreMap | null;
	setMap: (map: MapLibreMap | null) => void;
	camera: Camera | null;
	setCamera: (c: Camera | null) => void;
	tab: string;
	setTab: (tab: string) => void;
	selected: ItemInfo | null;
	select: (info: ItemInfo | null) => void;
	/** Select what a click loads, unless something else was selected (or clicked) meanwhile (CodeRabbit). */
	selectLoaded: (load: Promise<ItemInfo>) => Promise<void>;
	results: ResultRow[];
	resultsTitle: string;
	setResults: (rows: ResultRow[], title: string) => void;
	/** Find: the search box's text, the search made from it, and a type listed from the type list. */
	findText: string;
	setFindText: (t: string) => void;
	query: string;
	/** Search: a new search takes the rings of the one before off the map (user: different finds piled up). */
	setQuery: (q: string) => void;
	listed: { label: string; icon: string | null } | null;
	/** List a type's items (its icon lit up on the map), in place of a search. */
	listType: (label: string, icon: string | null) => void;
	/** Empty Find: the box, the results and every ring it put on the map (the x button, Esc in the box or on the map). */
	clearFind: () => void;
	highlight: string | null;
	setHighlight: (type: string | null) => void;
	mode: MapMode;
	setMode: (mode: MapMode) => void;
	fly: { x: number; y: number; px?: number; n: number } | null;
	flyTo: (x: number, y: number, px?: number) => void;
	fitAtlas: number;
	requestFit: () => void;
	goto: Point | null;
	setGoto: (p: Point | null) => void;
	route: { path: number[]; message: string } | null;
	setRoute: (r: { path: number[]; message: string } | null) => void;
	replay: ReplayUi | null;
	setReplay: (r: ReplayUi | null) => void;
	patchReplay: (r: Partial<ReplayUi>) => void;
	filePick: FilePick | null;
	pickFiles: (p: FilePick | null) => void;
	prompt: Prompt | null;
	ask: (p: Prompt | null) => void;
	confirm: Confirm | null;
	askConfirm: (c: Confirm | null) => void;
	bookmarkEdit: BookmarkEdit | null;
	editBookmark: (b: BookmarkEdit | null) => void;
	sources: Point | null;
	showSources: (p: Point | null) => void;
	deleteAtlas: string | null;
	askDeleteAtlas: (json: string | null) => void;
	error: string | null;
	showError: (e: unknown) => void;
	frameLog: boolean;
	setFrameLog: (on: boolean) => void;
	/** Bookmark groups folded shut in the Bookmarks tab (user: as in the old window). */
	foldedGroups: string[];
	foldGroup: (name: string, folded: boolean) => void;
	/** Forget what belonged to the atlas open before (another atlas was opened, made or closed). */
	resetAtlas: () => void;
}

/** Counts selections: a click's answer that comes back after a newer selection is dropped. */
let selectSeq = 0;

export const useAppStore = create<AppStoreState>()((set) => ({
	map: null,
	setMap: (map) => set({ map }),
	camera: null,
	setCamera: (camera) => set({ camera }),
	tab: "find",
	setTab: (tab) => set({ tab }),
	selected: null,
	select: (selected) => {
		selectSeq++;
		set({ selected });
	},
	selectLoaded: async (load) => {
		const mine = ++selectSeq;
		const info = await load;
		if (mine === selectSeq) set({ selected: info });
	},
	results: [],
	resultsTitle: "",
	setResults: (results, resultsTitle) => set({ results, resultsTitle }),
	findText: "",
	setFindText: (findText) => set({ findText }),
	query: "",
	setQuery: (query) => set(query.trim() ? { query, highlight: null, goto: null } : { query }),
	listed: null,
	listType: (label, icon) => set({ findText: "", query: "", listed: { label, icon }, highlight: icon, goto: null }),
	clearFind: () =>
		set({ findText: "", query: "", listed: null, highlight: null, goto: null, results: [], resultsTitle: "" }),
	highlight: null,
	setHighlight: (highlight) => set({ highlight }),
	mode: { kind: "normal" },
	setMode: (mode) => set({ mode }),
	fly: null,
	flyTo: (x, y, px) => set((s) => ({ fly: { x, y, px, n: (s.fly?.n ?? 0) + 1 } })),
	fitAtlas: 0,
	requestFit: () => set((s) => ({ fitAtlas: s.fitAtlas + 1 })),
	goto: null,
	setGoto: (goto) => set({ goto }),
	route: null,
	setRoute: (route) => set({ route }),
	replay: null,
	setReplay: (replay) => set({ replay }),
	patchReplay: (r) => set((s) => (s.replay ? { replay: { ...s.replay, ...r } } : {})),
	filePick: null,
	pickFiles: (filePick) => set({ filePick }),
	prompt: null,
	ask: (prompt) => set({ prompt }),
	confirm: null,
	askConfirm: (confirm) => set({ confirm }),
	bookmarkEdit: null,
	editBookmark: (bookmarkEdit) => set({ bookmarkEdit }),
	sources: null,
	showSources: (sources) => set({ sources }),
	deleteAtlas: null,
	askDeleteAtlas: (deleteAtlas) => set({ deleteAtlas }),
	error: null,
	// an answer for the atlas open before isn't an error: the page just draws the new one
	showError: (e) => {
		if (isStale(e)) return;
		set({ error: e == null ? null : e instanceof Error ? e.message : String(e) });
	},
	frameLog: false,
	setFrameLog: (frameLog) => set({ frameLog }),
	foldedGroups: [],
	foldGroup: (name, folded) =>
		set((s) => ({
			foldedGroups: folded ? [...new Set([...s.foldedGroups, name])] : s.foldedGroups.filter((g) => g !== name),
		})),
	// the selection, search, highlight, route, replay, a placement or lasso waiting for a click, dialogs about one of
	// its items and the camera all belonged to the atlas open before (user: they showed or acted on the new one; the
	// new map opened at the old atlas's spot). Kept: the tab, the file picker and the atlas dialogs (not one atlas's).
	resetAtlas: () => {
		selectSeq++; // a click's selection still loading belongs to the atlas before (CodeRabbit)
		set({
			camera: null,
			selected: null,
			results: [],
			resultsTitle: "",
			query: "",
			findText: "",
			listed: null,
			highlight: null,
			mode: { kind: "normal" },
			fly: null,
			goto: null,
			route: null,
			replay: null,
			prompt: null,
			confirm: null,
			bookmarkEdit: null,
			sources: null,
		});
	},
}));

/** Stands for "a replay is open" in useAppStoreCalm (its contents left out). */
const REPLAY_OPEN = {} as ReplayUi;

/**
 * The whole store for components that read many of its parts, without the replay's position: the replay moves it
 * every frame, and every such component drew again each frame while playing (the page fell seconds behind and a
 * pause came late: user). `replay` here only says whether one is open.
 */
export function useAppStoreCalm(): AppStoreState {
	return useAppStore(useShallow((st) => ({ ...st, replay: st.replay ? REPLAY_OPEN : null })));
}
