import { useQueryClient } from "@tanstack/react-query";
import type { MapLayerMouseEvent, MapMouseEvent } from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { sameAtlas } from "@/api/Http";
import type { Bookmarks, SavedRoute } from "@/domain/bookmarks/Bookmarks";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { usePlayer, useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { savedRoute, useRoutes } from "@/hooks/map/UseRoutes";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
import type { Point } from "@/logic/Geo";
import type { IconLayer3D } from "@/logic/IconLayer3D";
import { modeCursor, modeHint } from "@/logic/ModeHint";
import type { ModelLayer3D } from "@/logic/ModelLayer3D";
import { layerOn } from "@/logic/map/AtlasLayers";
import { wasDrag } from "@/logic/map/PanGuard";
import type { PathLayer3D } from "@/logic/PathLayer3D";
import { pickItem } from "@/logic/Pick";
import { addMap, legsOf, nearestOn, removeMap, savedRouteOf } from "@/logic/SavedRoutes";
import { type MapMode, useAppStore } from "@/store/AppStore";
import { BiomeMenu } from "./BiomeMenu";
import { LassoDraw } from "./draw/LassoDraw";
import { MapMenu } from "./MapMenu";
import { RouteMenu } from "./RouteMenu";

const HOVER = ["maps", "landmarks", "bookmarks", "icons", "paths"];

/** Clicks, drags and keys on the map, by mode: select, draw a city biome, add a bookmark, place a screenshot by
 * hand, set your position, link two maps for a debug mark; and the right-click menu. */
export function MapInteraction() {
	const map = useMapLibre();
	const { geo, meta } = useMapView();
	const app = useAppClient();
	const queryClient = useQueryClient();
	const mode = useAppStore((s) => s.mode);
	const setMode = useAppStore((s) => s.setMode);
	const select = useAppStore((s) => s.select);
	const setTab = useAppStore((s) => s.setTab);
	const editBookmark = useAppStore((s) => s.editBookmark);
	const tab = useAppStore((s) => s.tab);
	const setRouteDraft = useAppStore((s) => s.setRouteDraft);
	const bookmarks = useBookmarks();
	const showError = useAppStore((s) => s.showError);
	const settings = useSettings();
	const update = useUpdateSettings();
	const atlasFile = usePlayer().atlas; // your position is kept with the atlas it was set in
	const debug = !!useAppState().data?.debug;
	const graph = useRouteGraph(mode.kind === "player" || mode.kind === "route" || mode.kind === "route-edit");
	// a saved route being changed (Add / Remove maps): as it is after the last click, so a click before the list
	// came back builds on it
	const editedRoute = useRef<{ id: number; route: SavedRoute } | null>(null);
	const routes = useRoutes();
	const [menu, setMenu] = useState<{ x: number; y: number; at: Point; hit: ItemInfo | null } | null>(null);
	const lassoSeq = useRef(0);
	const [lasso, setLasso] = useState<{ polygon: Point[]; x: number; y: number; maps: number } | null>(null);
	// a route found between the two maps clicked (Route), waiting for Track now or Save route
	const [routeMenu, setRouteMenu] = useState<{ path: number[]; x: number; y: number } | null>(null);
	const drag = useRef<{ start: Point; centre: Point } | null>(null);

	const atlasAt = useCallback((e: MapMouseEvent): Point => geo.toAtlas(e.lngLat.lng, e.lngLat.lat), [geo]);
	// the ground point under the mouse (in 3D, whatever stands there is picked from the picture first: pick3d)
	const clickAt = atlasAt;
	const pick = useCallback(
		(at: Point) => app.pick(at[0], at[1], geo.pxPerUnit(map.getZoom()), settings?.layers),
		[app, geo, map, settings?.layers],
	);

	// tilted: what is drawn under the mouse, read back from the picture (the icon in front, then a path, then a
	// model: a map node's pillar or a landmark's structure), else what lies on the ground there
	const pick3d = useCallback(
		async (e: MapMouseEvent): Promise<ItemInfo | null> => {
			if (map.getPitch() > 1) {
				const impl = <T,>(id: string) =>
					(map.getLayer(id) as unknown as { implementation?: T } | undefined)?.implementation;
				const icons = impl<IconLayer3D>("icons-3d-gl");
				const id = icons ? await icons.pickAt(e.point.x, e.point.y) : null;
				if (id !== null) return app.getInfo("icon", id);
				const paths = impl<PathLayer3D>("paths-3d-gl");
				const pid = paths ? await paths.pickAt(e.point.x, e.point.y) : null;
				if (pid !== null) return app.getInfo("path", pid);
				const models = impl<ModelLayer3D>("models-3d-gl");
				const hit = models ? pickItem(await models.pickAt(e.point.x, e.point.y)) : null;
				if (hit) return app.getInfo(hit.kind, hit.id);
			}
			return pick(clickAt(e));
		},
		[map, app, pick, clickAt],
	);

	// Adjust route (a saved route's right-click menu in Bookmarks): a map clicked goes on the route (past an end, or a
	// branch off its side), a map right-clicked comes off it with the rest of its leg (user)
	const adjustRoute = useCallback(
		async (at: Point, add: boolean, started: MapMode) => {
			if (started.kind !== "route-edit" || !graph) return;
			const hit = await pick(at);
			if (useAppStore.getState().mode !== started) return; // (left meanwhile)
			const picked = hit?.kind === "node" ? hit.id : (hit?.node ?? graph.nearest(at[0], at[1]));
			const listed = queryClient
				.getQueryData<Bookmarks>(AppQueryKeys.bookmarks)
				?.groups.flatMap((g) => g.items)
				.find((b) => b.id === started.id)?.route;
			const before = editedRoute.current?.id === started.id ? editedRoute.current.route : listed;
			if (!before) {
				setMode({ kind: "normal" });
				return;
			}
			const legs = legsOf(before, graph);
			if (!legs) {
				showError("This route's maps aren't on this atlas any more.", true);
				return;
			}
			// taking maps off: the route's own map nearest the click, near enough (an icon beside it can belong to
			// another map)
			const reach = ROUTE_EDIT_REACH_PX / geo.pxPerUnit(map.getZoom());
			const node = add ? picked : (nearestOn(legs, graph, at, reach) ?? picked);
			if (node === null) return;
			const next = add ? addMap(legs, node, graph) : removeMap(legs, node);
			if (typeof next === "string") {
				showError(next, true);
				return;
			}
			const route = savedRouteOf(next, graph);
			editedRoute.current = { id: started.id, route };
			try {
				await app.setBookmarkRoute(started.id, route);
			} catch (err) {
				editedRoute.current = null; // (the list holds what was saved)
				throw err;
			}
		},
		[graph, pick, queryClient, setMode, showError, geo, map, app],
	);

	// --- clicks
	useEffect(() => {
		const onClick = async (e: MapMouseEvent) => {
			if (wasDrag()) return; // a pan, not a click
			const at = mode.kind === "normal" ? clickAt(e) : atlasAt(e);
			// what was clicked, for a mode still on once the answer comes: left meanwhile (Esc, another tab, another
			// mode), the click is dropped (it opened the bookmark dialog after Add bookmark had ended: CodeRabbit)
			const pickHere = async () => {
				const hit = await pick(at);
				return useAppStore.getState().mode === mode ? { hit } : null;
			};
			try {
				switch (mode.kind) {
					case "normal": {
						const hit = await pick3d(e);
						select(hit);
						if (hit) setTab("find");
						break;
					}
					case "bookmark": {
						// a map that has a bookmark opens that one (before: a second bookmark on the same map)
						const still = await pickHere();
						if (!still) break;
						const { hit } = still;
						setMode({ kind: "normal" });
						editBookmark(bookmarkOf(hit) ?? newBookmark(hit, at));
						break;
					}
					case "player": {
						const still = await pickHere();
						if (!still) break;
						const { hit } = still;
						const node = hit?.kind === "node" ? hit.id : (hit?.node ?? graph?.nearest(at[0], at[1]) ?? null);
						const p = node !== null ? graph?.at(node) : undefined;
						if (node !== null && p) update.mutate({ ui: { player: { x: p[0], y: p[1], node, atlas: atlasFile } } });
						setMode({ kind: "normal" });
						break;
					}
					case "route": {
						// the first map, then the last: the route between them, fewest maps (user)
						const still = await pickHere();
						if (!still || !graph) break;
						const { hit } = still;
						const node = hit?.kind === "node" ? hit.id : (hit?.node ?? graph.nearest(at[0], at[1]));
						if (node === null) break;
						if (mode.from === null) {
							setMode({ kind: "route", from: node });
							// ringed at once (user: nothing showed until the second map)
							setRouteDraft([node]);
							break;
						}
						setMode({ kind: "normal" });
						const path = node === mode.from ? null : graph.shortest(mode.from, (u) => u === node);
						if (!path) {
							setRouteDraft(null);
							showError(`No known path from map #${mode.from} to map #${node}.`, true);
							break;
						}
						setRouteDraft(path);
						setRouteMenu({ path, x: e.point.x, y: e.point.y });
						break;
					}
					case "route-edit":
						await adjustRoute(at, true, mode); // a left click adds a map (user)
						break;
					case "debug-link": {
						const still = await pickHere();
						if (!still) break;
						const { hit } = still;
						const other = hit?.kind === "node" ? hit.id : (hit?.node ?? null);
						if (other !== null && other !== mode.from) {
							await app.addDebugMark({
								kind: "missing path",
								reason: "there should be a path between these maps",
								note: mode.note,
								maps: [mode.from, other],
							});
						} else showError("Debug: no second map clicked - link cancelled.");
						setMode({ kind: "normal" });
						break;
					}
					default:
						break;
				}
			} catch (err) {
				showError(err);
			}
		};
		map.on("click", onClick);
		return () => {
			map.off("click", onClick);
		};
	}, [
		map,
		mode,
		atlasAt,
		pick,
		select,
		setTab,
		editBookmark,
		setRouteDraft,
		setMode,
		graph,
		update,
		app,
		showError,
		clickAt,
		pick3d,
		atlasFile,
		adjustRoute,
	]);

	// another mode, or another route: what was changed is in the list now
	useEffect(() => {
		if (mode.kind !== "route-edit" || editedRoute.current?.id !== mode.id) editedRoute.current = null;
	}, [mode]);

	// Route left another way than its menu (another mode, another tab's button): its picked maps go
	useEffect(() => {
		if (mode.kind !== "route" && !routeMenu) setRouteDraft(null);
	}, [mode, routeMenu, setRouteDraft]);

	// a saved route deleted (its row, its group, Delete with it ticked): what was going on with it ends: tracking it,
	// lighting it up, adjusting it (user: deleting a route while adjusting it left the mode on, and a click went to it)
	useEffect(() => {
		const groups = bookmarks.data?.groups;
		if (groups) useAppStore.getState().bookmarksAre(new Set(groups.flatMap((g) => g.items.map((b) => b.id))));
	}, [bookmarks.data]);

	// --- double click: place the ghost, else zoom in
	useEffect(() => {
		const onDouble = (e: MapMouseEvent) => {
			if (mode.kind === "ghost") {
				e.preventDefault();
				void placeGhost();
				return;
			}
			map.easeTo({ center: e.lngLat, zoom: Math.min(map.getMaxZoom(), map.getZoom() + 1), duration: 300 });
		};
		const placeGhost = async () => {
			if (mode.kind !== "ghost") return;
			try {
				await app.placeByHand(mode.ghost.path, mode.centre[0], mode.centre[1]);
				setMode({ kind: "normal" });
			} catch (err) {
				showError(err);
			}
		};
		map.on("dblclick", onDouble);
		return () => {
			map.off("dblclick", onDouble);
		};
	}, [map, mode, app, setMode, showError]);

	// --- the lasso (drawn by LassoDraw): how many maps it holds, then their biome is picked
	const lassoDrawn = useCallback(
		async (polygon: Point[], at: { x: number; y: number }) => {
			if (polygon.length < 3) {
				setMode({ kind: "normal" });
				return;
			}
			const mine = ++lassoSeq.current;
			// another lasso drawn meanwhile, or another atlas opened (its answer can be accepted before the switch
			// shows: CodeRabbit)
			const still = sameAtlas();
			const current = () => mine === lassoSeq.current && still();
			try {
				const { maps } = await app.lassoCount(polygon);
				if (!current()) return;
				if (!maps) {
					showError("No maps inside the lasso.", true); // (closes on the next click)
					setMode({ kind: "normal" });
					return;
				}
				setLasso({ polygon, x: at.x, y: at.y, maps });
			} catch (err) {
				if (current()) showError(err);
			}
		},
		[app, setMode, showError],
	);
	const lassoStarted = useCallback(() => {
		lassoSeq.current++; // the one before's count, still coming, is dropped
		setLasso(null);
	}, []);

	// --- drags: the ghost (panning is MapPan's, off in these modes)
	useEffect(() => {
		map.getCanvas().style.cursor = modeCursor(mode);
		if (mode.kind !== "ghost") return;

		const down = (e: MapMouseEvent) => {
			if (e.originalEvent.button === 0) drag.current = { start: atlasAt(e), centre: mode.centre };
		};
		const move = (e: MapMouseEvent) => {
			if (!drag.current) return;
			const [x, y] = atlasAt(e);
			const { start, centre } = drag.current;
			setMode({ ...mode, centre: [centre[0] + x - start[0], centre[1] + y - start[1]] });
		};
		const up = () => {
			drag.current = null;
		};
		map.on("mousedown", down);
		map.on("mousemove", move);
		map.on("mouseup", up);
		return () => {
			map.off("mousedown", down);
			map.off("mousemove", move);
			map.off("mouseup", up);
		};
	}, [map, mode, atlasAt, setMode]);

	// --- keys: Esc cancels, Enter places the ghost
	useEffect(() => {
		const onKey = async (e: KeyboardEvent) => {
			const t = e.target as HTMLElement | null;
			if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
			if (e.key === "Escape" && mode.kind !== "normal") {
				if (mode.kind === "route") setRouteDraft(null); // (its first map's ring goes too; a route tracked stays)
				drag.current = null; // a ghost drag ends too (it moved the next ghost: CodeRabbit)
				lassoSeq.current++;
				setLasso(null);
				setMode({ kind: "normal" });
			} else if (e.key === "Escape") {
				// with nothing to cancel, Esc empties Find and takes its rings off the map (user: it only worked in the box)
				useAppStore.getState().clearFind();
			} else if (e.key === "Enter" && mode.kind === "ghost") {
				try {
					await app.placeByHand(mode.ghost.path, mode.centre[0], mode.centre[1]);
					setMode({ kind: "normal" });
				} catch (err) {
					showError(err);
				}
			} else if (e.key === "0") useAppStore.getState().requestFit();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [mode, setMode, app, showError, setRouteDraft]);

	// --- right click
	useEffect(() => {
		const onMenu = async (e: MapMouseEvent) => {
			if (mode.kind === "route-edit") {
				// a right click takes a map off the route being adjusted (user)
				try {
					await adjustRoute(atlasAt(e), false, mode);
				} catch (err) {
					showError(err);
				}
				return;
			}
			if (mode.kind !== "normal") return;
			const at = clickAt(e);
			let hit: ItemInfo | null = null;
			try {
				hit = await pick3d(e);
			} catch {
				hit = null;
			}
			if (hit) select(hit);
			setMenu({ x: e.point.x, y: e.point.y, at, hit });
		};
		map.on("contextmenu", onMenu);
		return () => {
			map.off("contextmenu", onMenu);
		};
	}, [map, mode, select, clickAt, pick3d, adjustRoute, atlasAt, showError]);

	// --- pointer over things that can be clicked
	useEffect(() => {
		const enter = () => {
			if (useAppStore.getState().mode.kind === "normal") map.getCanvas().style.cursor = "pointer";
		};
		const leave = () => {
			if (useAppStore.getState().mode.kind === "normal") map.getCanvas().style.cursor = "";
		};
		const layers = HOVER.filter((id) => map.getLayer(id));
		for (const id of layers) {
			map.on("mouseenter", id, enter as (e: MapLayerMouseEvent) => void);
			map.on("mouseleave", id, leave as (e: MapLayerMouseEvent) => void);
		}
		return () => {
			for (const id of layers) {
				map.off("mouseenter", id, enter as (e: MapLayerMouseEvent) => void);
				map.off("mouseleave", id, leave as (e: MapLayerMouseEvent) => void);
			}
		};
	}, [map]);

	const chooseRoute = (what: "track" | "save" | null) => {
		const r = routeMenu;
		setRouteMenu(null);
		setRouteDraft(null); // tracked, saved or cancelled: the route tracked before stays unless it's Track now
		if (!r) return;
		if (what === "track") routes.trackRoute(r.path);
		else if (what === "save" && graph) {
			const start = graph.at(r.path[0]) ?? [0, 0];
			// numbered after the routes saved so far: route1, route2, ...
			const saved = (bookmarks.data?.groups ?? []).flatMap((g) => g.items).filter((b) => b.route).length;
			editBookmark({
				id: null,
				x: start[0],
				y: start[1],
				name: `route${saved + 1}`,
				group: "Routes",
				note: "",
				route: savedRoute(graph, r.path),
			});
		}
	};

	const chooseBiome = async (biome: string | null) => {
		const l = lasso;
		setLasso(null);
		setMode({ kind: "normal" });
		if (l && biome === null) app.log(["Biome select: cancelled, nothing changed"]).catch(() => {});
		if (!l || biome === null) return;
		try {
			await app.setBiome(l.polygon, biome);
		} catch (err) {
			showError(err);
		}
	};

	return (
		<>
			{mode.kind === "lasso" && <LassoDraw onStart={lassoStarted} onDrawn={lassoDrawn} />}
			{menu && (
				<MapMenu
					x={menu.x}
					y={menu.y}
					at={menu.at}
					hit={menu.hit}
					meta={meta}
					debug={debug}
					onClose={() => {
						setMenu(null);
						void queryClient.invalidateQueries({ queryKey: AppQueryKeys.debug });
					}}
				/>
			)}
			{lasso && <BiomeMenu x={lasso.x} y={lasso.y} maps={lasso.maps} meta={meta} onChoose={chooseBiome} />}
			{routeMenu && (
				<RouteMenu
					x={routeMenu.x}
					y={routeMenu.y}
					from={routeMenu.path[0]}
					to={routeMenu.path[routeMenu.path.length - 1]}
					maps={routeMenu.path.length - 1}
					onChoose={chooseRoute}
				/>
			)}
			{/* what a click does now, over the map itself (user: Add bookmark only said so in the side panel) */}
			{/* the notes over the map: what a click does now, and that bookmarks are hidden while their tab is open
			    (they have their own switch: a lasting notice, user) */}
			<div className="pointer-events-none absolute top-2 left-1/2 z-10 flex -translate-x-1/2 flex-col items-center gap-1.5">
				{mode.kind !== "normal" && !lasso && (
					<div className="rounded-md border border-gold/60 bg-card/95 px-3 py-1.5 text-sm text-gold shadow">
						{modeHint(mode)}
					</div>
				)}
				{tab === "bookmarks" && settings && !layerOn(settings, "Bookmarks") && (
					<div
						role="status"
						className="pointer-events-auto flex items-center gap-3 rounded-md border bg-card/95 px-3 py-1.5 text-sm shadow"
					>
						Bookmarks are currently hidden
						<button
							type="button"
							className="text-gold hover:underline"
							onClick={() => update.mutate({ layers: { Bookmarks: true } })}
						>
							Show them
						</button>
					</div>
				)}
			</div>
		</>
	);
}

const ROUTE_EDIT_REACH_PX = 24; // Remove maps: a click this near (screen px) to a map of the route takes that map
