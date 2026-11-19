import { useQueryClient } from "@tanstack/react-query";
import type { MapLayerMouseEvent, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { Meta } from "@/domain/app/Meta";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { usePlayer, useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import { bookmarkOf, newBookmark } from "@/logic/BookmarkOf";
import type { Geo, Point } from "@/logic/Geo";
import type { IconLayer3D } from "@/logic/IconLayer3D";
import { EMPTY, setData } from "@/logic/MapStyle";
import { modeCursor, modeHint } from "@/logic/ModeHint";
import type { ModelLayer3D } from "@/logic/ModelLayer3D";
import type { PathLayer3D } from "@/logic/PathLayer3D";
import { pickItem } from "@/logic/Pick";
import { useAppStore } from "@/store/AppStore";
import { BiomeMenu } from "./BiomeMenu";
import { MapMenu } from "./MapMenu";

const HOVER = ["maps", "landmarks", "bookmarks", "icons", "paths"];

/** Clicks, drags and keys on the map, by mode: select, draw a city biome, add a bookmark, place a screenshot by
 * hand, set your position, link two maps for a debug mark; and the right-click menu. */
export function MapInteraction({ map, geo, meta }: { map: MapLibreMap; geo: Geo; meta: Meta }) {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const mode = useAppStore((s) => s.mode);
	const setMode = useAppStore((s) => s.setMode);
	const select = useAppStore((s) => s.select);
	const setTab = useAppStore((s) => s.setTab);
	const editBookmark = useAppStore((s) => s.editBookmark);
	const bookmarks = useBookmarks();
	const showError = useAppStore((s) => s.showError);
	const settings = useSettings();
	const update = useUpdateSettings();
	const atlasFile = usePlayer().atlas; // your position is kept with the atlas it was set in
	const debug = !!useAppState().data?.debug;
	const graph = useRouteGraph(mode.kind === "player");
	const [menu, setMenu] = useState<{ x: number; y: number; at: Point; hit: ItemInfo | null } | null>(null);
	const lassoSeq = useRef(0);
	const [lasso, setLasso] = useState<{ polygon: Point[]; x: number; y: number; maps: number } | null>(null);
	const drawing = useRef<Point[] | null>(null);
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

	// --- clicks
	useEffect(() => {
		const onClick = async (e: MapMouseEvent) => {
			const at = mode.kind === "normal" ? clickAt(e) : atlasAt(e);
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
						const hit = await pick(at);
						setMode({ kind: "normal" });
						editBookmark(bookmarkOf(hit, bookmarks.data) ?? newBookmark(hit, at));
						break;
					}
					case "player": {
						const hit = await pick(at);
						const node = hit?.kind === "node" ? hit.id : (hit?.node ?? graph?.nearest(at[0], at[1]) ?? null);
						const p = node !== null ? graph?.at(node) : undefined;
						if (node !== null && p) update.mutate({ ui: { player: { x: p[0], y: p[1], node, atlas: atlasFile } } });
						setMode({ kind: "normal" });
						break;
					}
					case "debug-link": {
						const hit = await pick(at);
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
		bookmarks.data,
		setMode,
		graph,
		update,
		app,
		showError,
		clickAt,
		pick3d,
		atlasFile,
	]);

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

	// --- drags: the lasso, the ghost
	useEffect(() => {
		const dragging = mode.kind === "lasso" || mode.kind === "ghost";
		void dragging; // panning is AtlasMap's own drag (it stays off in these modes)
		map.getCanvas().style.cursor = modeCursor(mode);

		const down = (e: MapMouseEvent) => {
			if (e.originalEvent.button !== 0) return;
			if (mode.kind === "lasso") {
				drawing.current = [atlasAt(e)];
				setLasso(null);
			} else if (mode.kind === "ghost") drag.current = { start: atlasAt(e), centre: mode.centre };
		};
		const move = (e: MapMouseEvent) => {
			if (mode.kind === "lasso" && drawing.current) {
				drawing.current.push(atlasAt(e));
				const ring = geo.ring(drawing.current);
				setData(map, "lasso", {
					type: "Feature",
					geometry: { type: "Polygon", coordinates: [ring.length > 3 ? ring : [...ring, ...ring]] },
					properties: {},
				});
			} else if (mode.kind === "ghost" && drag.current) {
				const [x, y] = atlasAt(e);
				const { start, centre } = drag.current;
				setMode({ ...mode, centre: [centre[0] + x - start[0], centre[1] + y - start[1]] });
			}
		};
		const up = async (e: MapMouseEvent) => {
			if (mode.kind === "ghost") {
				drag.current = null;
				return;
			}
			if (mode.kind !== "lasso" || !drawing.current) return;
			const polygon = drawing.current;
			drawing.current = null;
			if (polygon.length < 3) {
				setData(map, "lasso", EMPTY);
				setMode({ kind: "normal" });
				return;
			}
			const mine = ++lassoSeq.current;
			try {
				const { maps } = await app.lassoCount(polygon);
				if (mine !== lassoSeq.current) return; // another lasso was drawn meanwhile (CodeRabbit)
				if (!maps) {
					showError("No maps inside the lasso.");
					setData(map, "lasso", EMPTY);
					setMode({ kind: "normal" });
					return;
				}
				setLasso({ polygon, x: e.point.x, y: e.point.y, maps });
			} catch (err) {
				showError(err);
			}
		};
		map.on("mousedown", down);
		map.on("mousemove", move);
		map.on("mouseup", up);
		return () => {
			map.off("mousedown", down);
			map.off("mousemove", move);
			map.off("mouseup", up);
		};
	}, [map, geo, mode, atlasAt, setMode, app, showError]);

	// --- keys: Esc cancels, Enter places the ghost
	useEffect(() => {
		const onKey = async (e: KeyboardEvent) => {
			const t = e.target as HTMLElement | null;
			if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
			if (e.key === "Escape" && mode.kind !== "normal") {
				drawing.current = null;
				drag.current = null; // a ghost drag ends too (it moved the next ghost: CodeRabbit)
				lassoSeq.current++;
				setData(map, "lasso", EMPTY);
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
	}, [map, mode, setMode, app, showError]);

	// --- right click
	useEffect(() => {
		const onMenu = async (e: MapMouseEvent) => {
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
	}, [map, mode, select, clickAt, pick3d]);

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

	const chooseBiome = async (biome: string | null) => {
		const l = lasso;
		setLasso(null);
		setData(map, "lasso", EMPTY);
		setMode({ kind: "normal" });
		if (!l || biome === null) return;
		try {
			await app.setBiome(l.polygon, biome);
		} catch (err) {
			showError(err);
		}
	};

	return (
		<>
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
			{/* what a click does now, over the map itself (user: Add bookmark only said so in the side panel) */}
			{mode.kind !== "normal" && !lasso && (
				<div className="pointer-events-none absolute top-2 left-1/2 z-10 -translate-x-1/2 rounded-md border border-gold/60 bg-card/95 px-3 py-1.5 text-sm text-gold shadow">
					{modeHint(mode)}
				</div>
			)}
		</>
	);
}
