import type { Map as MapLibreMap } from "maplibre-gl";
import { create } from "zustand";
import { useShallow } from "zustand/shallow";
import { isStale } from "@/api/Http";
import type { Ghost } from "@/domain/adding/Ghost";
import type { SavedRoute } from "@/domain/bookmarks/Bookmarks";
import type { ResultRow } from "@/domain/find/SearchResult";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import type { Point } from "@/logic/Geo";

/** The tabs that became pages of another (the side panel: Find, View, Saved, Atlases): id -> [tab, page]. The app
 * still asks for "auto" (screenshots waiting for a place) and the page's own code for the others. */
export const PAGE_OF: Record<string, [string, string]> = {
	auto: ["atlases", "auto"],
	route: ["bookmarks", "route"],
};

/** The pages of the log drawer (under the map, from the status line: it was the side panel's Log tab). */
export const LOG_PAGES = new Set(["log", "debug"]);

/** What a click on the map does. */

export type MapMode =
	| { kind: "normal" }
	| { kind: "lasso" }
	| { kind: "bookmark" }
	| { kind: "player" }
	| { kind: "ghost"; ghost: Ghost; centre: Point }
	| { kind: "debug-link"; from: number; note: string }
	// Route (top bar): the first map picked, then the last
	| { kind: "route"; from: number | null }
	// Adjust route on a saved route (Bookmarks, right-click): a map clicked goes on it, a map right-clicked comes off
	| { kind: "route-edit"; id: number };

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
	/** Pick one of these (a dropdown) instead of typing. */
	choices?: string[];
	onOk: (value: string) => void;
};

export type Confirm = {
	title: string;
	text: string;
	yes: string;
	danger?: boolean;
	onYes: () => void;
};

export type BookmarkEdit = {
	id: number | null;
	x: number;
	y: number;
	name: string;
	group: string;
	note: string;
	/** Saving a route (Save route): it goes in as a route bookmark. */
	route?: SavedRoute;
};

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
	/** Open a tab (the side panel opens with it), or a page of one by its own id ("auto", "route": they were tabs of
	 * their own); "log" and "debug" open the log drawer on that page. */
	setTab: (tab: string) => void;
	/** The side panel's drawer is open (the rail's tab clicked again closes it, for more map). */
	panelOpen: boolean;
	setPanelOpen: (open: boolean) => void;
	/** The View tab's sections open ("2d:Paths", "3d:Icons"…), kept while the tab is closed (PO: an accordion). */
	viewOpen: string[];
	toggleViewSection: (key: string) => void;
	/** The log drawer under the map, and its page (log / debug). */
	logOpen: boolean;
	logPage: string;
	setLogOpen: (open: boolean) => void;
	setLogPage: (page: string) => void;
	/** The page each tab with pages shows (Atlases: atlases / auto; Bookmarks: bookmarks / route; Log: log / debug). */
	pages: Record<string, string>;
	setPage: (tab: string, page: string) => void;
	/** The layers shown because a View setting of theirs is in use (RevealWhileUsed; let go when you leave the tab). */
	editing: string[];
	/** A layer's setting is in use: it shows until the returned release (user: only while a slider is held or a
	 * dropdown open; no timer). */
	hold: (layer: string) => () => void;
	selected: ItemInfo | null;
	select: (info: ItemInfo | null) => void;
	/** The saved route lit up on the map (its bookmark id): clicked in Bookmarks, or being changed (user: it didn't
	 * light up as a bookmark does). Selecting anything else puts it out. */
	routeLit: number | null;
	lightRoute: (id: number | null) => void;
	/** The bookmarks there are now: a saved route deleted ends what was going on with it (tracking it, lit up,
	 * adjusting it). */
	bookmarksAre: (ids: Set<number>) => void;
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
	/** Find's kinds of results shown (its pills: maps, icons, places, bookmarks; paths always). */
	findKinds: string[];
	toggleFindKind: (kind: string) => void;
	listed: { label: string; icon: string | null } | null;
	/** List a type's items (its icon lit up on the map), in place of a search. */
	listType: (label: string, icon: string | null) => void;
	/** Empty Find: the box, the results and every ring it put on the map (the x button, Esc in the box or on the map). */
	clearFind: () => void;
	highlight: string | null;
	setHighlight: (type: string | null) => void;
	mode: MapMode;
	/** A map mode starts or ends; none starts while the timelapse is open (user: Route, then the timelapse, and a
	 * click in it took a map). */
	setMode: (mode: MapMode) => void;
	/** Biome select's menu is up (its note would still say to draw). */
	lassoAsked: boolean;
	fly: { x: number; y: number; px?: number; n: number } | null;
	flyTo: (x: number, y: number, px?: number) => void;
	fitAtlas: number;
	requestFit: () => void;
	/** Fit an area of the atlas in the view (a saved route: its whole line, with room round it). */
	fitTo: { box: [number, number, number, number]; n: number } | null;
	fitArea: (box: [number, number, number, number]) => void;
	goto: Point | null;
	setGoto: (p: Point | null) => void;
	/** The route shown; `at` while tracking it (Track now): the place in it of the map you are on. */
	route: RouteShown | null;
	setRoute: (r: RouteShown | null) => void;
	/** Route (top bar) while its maps are picked: the first map, then the route found, until Track now / Save route /
	 * Cancel. Apart from `route`, so a route tracked meanwhile stays (user: the first click replaced it, Esc threw
	 * it away). */
	routeDraft: number[] | null;
	setRouteDraft: (path: number[] | null) => void;
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
	/** The error is a brief note about the last click (no maps inside a lasso): it closes on the next click. */
	errorBrief: boolean;
	showError: (e: unknown, brief?: boolean) => void;
	frameLog: boolean;
	setFrameLog: (on: boolean) => void;
	/** Forget what belonged to the atlas open before (another atlas was opened, made or closed). */
	resetAtlas: () => void;
}

/** The route on the map. While it is tracked (Track now, Start tracking now): `at`, the place in it of the map you are
 * on (its own marker: tracking leaves your position as it is, user: deleting a tracked route left a stray "I'm
 * here"), and `saved`, the saved route's bookmark when it is one (deleting it ends the tracking). */
export type RouteShown = { path: number[]; message: string; at?: number; saved?: number };

/** The View settings in use, per layer (AppStoreState.hold). */
const holds = new Map<string, number>();
let holdEra = 0;
/** Let go of every View setting held (another atlas; a test's end: the registry is outside the store). */
export function releaseHolds(): void {
	useAppStore.setState(letGoAll());
}

function letGoAll(): { editing: string[] } {
	holds.clear();
	holdEra++;
	return { editing: [] };
}

/** Counts selections: a click's answer that comes back after a newer selection is dropped. */
let selectSeq = 0;

export const useAppStore = create<AppStoreState>()((set) => ({
	map: null,
	setMap: (map) => set({ map }),
	camera: null,
	setCamera: (camera) => set({ camera }),
	tab: "find",
	// leaving the Saved tab ends "Adjust route" (its maps are picked there). Add bookmark is a map tool of the top bar
	// now: it stays on in any tab
	setTab: (asked) =>
		set((st) => {
			if (LOG_PAGES.has(asked)) return { logOpen: true, logPage: asked };
			const [tab, page] = PAGE_OF[asked] ?? [asked, null];
			return {
				tab,
				panelOpen: true,
				// leaving the View tab: the layers its settings showed go back to their switches
				...(tab !== st.tab && st.editing.length ? letGoAll() : {}),
				...(page ? { pages: { ...st.pages, [tab]: page } } : {}),
				...(st.mode.kind === "route-edit" && tab !== "bookmarks" ? { mode: { kind: "normal" } as MapMode } : {}),
			};
		}),
	panelOpen: true,
	// closing the drawer is leaving its tab for the View settings held (their layers go back to their switches)
	setPanelOpen: (panelOpen) => set((st) => ({ panelOpen, ...(!panelOpen && st.editing.length ? letGoAll() : {}) })),
	viewOpen: ["2d:Paths", "2d:Maps", "3d:Paths"],
	toggleViewSection: (key) =>
		set((st) => ({
			viewOpen: st.viewOpen.includes(key) ? st.viewOpen.filter((k) => k !== key) : [...st.viewOpen, key],
		})),
	logOpen: false,
	logPage: "log",
	setLogOpen: (logOpen) => set({ logOpen }),
	setLogPage: (logPage) => set({ logPage }),
	pages: {},
	setPage: (tab, page) => set((st) => ({ pages: { ...st.pages, [tab]: page } })),
	editing: [],
	hold: (layer) => {
		const era = holdEra;
		holds.set(layer, (holds.get(layer) ?? 0) + 1);
		set({ editing: [...holds.keys()] });
		let done = false;
		return () => {
			if (done || era !== holdEra) return; // (let go twice, or all let go meanwhile: the tab changed)
			done = true;
			const n = (holds.get(layer) ?? 1) - 1;
			if (n > 0) holds.set(layer, n);
			else holds.delete(layer);
			useAppStore.setState({ editing: [...holds.keys()] });
		};
	},
	selected: null,
	select: (selected) => {
		selectSeq++;
		set({ selected, routeLit: null });
	},
	selectLoaded: async (load) => {
		const mine = ++selectSeq;
		const info = await load;
		if (mine === selectSeq) set({ selected: info, routeLit: null });
	},
	routeLit: null,
	bookmarksAre: (ids) =>
		set((st) => ({
			...(st.route?.saved !== undefined && !ids.has(st.route.saved) ? { route: null } : {}),
			...(st.routeLit !== null && !ids.has(st.routeLit) ? { routeLit: null } : {}),
			...(st.mode.kind === "route-edit" && !ids.has(st.mode.id) ? { mode: { kind: "normal" } as MapMode } : {}),
		})),
	// another route lit up while one is adjusted: the adjusting ends (it stayed on the first: review)
	lightRoute: (routeLit) => {
		selectSeq++;
		set((st) => ({
			routeLit,
			...(routeLit !== null ? { selected: null } : {}),
			...(st.mode.kind === "route-edit" && st.mode.id !== routeLit ? { mode: { kind: "normal" } as MapMode } : {}),
		}));
	},
	results: [],
	resultsTitle: "",
	setResults: (results, resultsTitle) => set({ results, resultsTitle }),
	findText: "",
	setFindText: (findText) => set({ findText }),
	query: "",
	setQuery: (query) => set(query.trim() ? { query, highlight: null, goto: null } : { query }),
	// icons off at first: a map lists its icons, so a search for one finds its maps (user), each icon again was twice
	findKinds: ["node", "landmark", "bookmark"],
	toggleFindKind: (kind) =>
		set((st) => ({
			findKinds: st.findKinds.includes(kind) ? st.findKinds.filter((k) => k !== kind) : [...st.findKinds, kind],
		})),
	listed: null,
	listType: (label, icon) => set({ findText: "", query: "", listed: { label, icon }, highlight: icon, goto: null }),
	clearFind: () =>
		set({ findText: "", query: "", listed: null, highlight: null, goto: null, results: [], resultsTitle: "" }),
	highlight: null,
	setHighlight: (highlight) => set({ highlight }),
	mode: { kind: "normal" },
	// refused while the timelapse is open, and said so (user: it was dropped without a word, not even in the log)
	setMode: (mode) =>
		set((st) =>
			st.replay && mode.kind !== "normal"
				? { error: "That doesn't work while the timelapse is open: close it first.", errorBrief: true }
				: { mode },
		),
	lassoAsked: false,
	fly: null,
	flyTo: (x, y, px) => set((s) => ({ fly: { x, y, px, n: (s.fly?.n ?? 0) + 1 } })),
	fitAtlas: 0,
	requestFit: () => set((s) => ({ fitAtlas: s.fitAtlas + 1 })),
	fitTo: null,
	fitArea: (box) => set((s) => ({ fitTo: { box, n: (s.fitTo?.n ?? 0) + 1 } })),
	goto: null,
	setGoto: (goto) => set({ goto }),
	route: null,
	// tracking another route while adjusting one ends the adjusting (map clicks went on changing it: CodeRabbit)
	setRoute: (route) =>
		set((st) => ({
			route,
			...(st.mode.kind === "route-edit" && route?.at !== undefined && route.saved !== st.mode.id
				? { mode: { kind: "normal" } as MapMode }
				: {}),
		})),
	routeDraft: null,
	setRouteDraft: (routeDraft) => set({ routeDraft }),
	replay: null,
	// opening the timelapse ends a map mode and Route's picked maps: it takes the map (user)
	setReplay: (replay) =>
		set((st) => ({
			replay,
			...(replay && !st.replay ? { mode: { kind: "normal" } as MapMode, routeDraft: null } : {}),
		})),
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
	errorBrief: false,
	// an answer for the atlas open before isn't an error: the page just draws the new one
	showError: (e, brief = false) => {
		if (isStale(e)) return;
		set({ error: e == null ? null : e instanceof Error ? e.message : String(e), errorBrief: e != null && brief });
	},
	frameLog: false,
	setFrameLog: (frameLog) => set({ frameLog }),
	// the selection, search, highlight, route, replay, a placement or lasso waiting for a click, dialogs about one of
	// its items and the camera all belonged to the atlas open before (user: they showed or acted on the new one; the
	// new map opened at the old atlas's spot). Kept: the tab, the file picker and the atlas dialogs (not one atlas's).
	resetAtlas: () => {
		selectSeq++; // a click's selection still loading belongs to the atlas before (CodeRabbit)
		set({
			...letGoAll(), // (View settings held belonged to the map before: review)
			camera: null,
			selected: null,
			routeLit: null,
			results: [],
			resultsTitle: "",
			query: "",
			findText: "",
			listed: null,
			highlight: null,
			mode: { kind: "normal" },
			fly: null,
			fitTo: null,
			goto: null,
			route: null,
			routeDraft: null,
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
