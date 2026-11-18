import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { Meta } from "@/domain/app/Meta";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings } from "@/hooks/app/UseSettings";
import { styleColour } from "@/logic/Colours";
import type { Geo } from "@/logic/Geo";
import { GroundFade } from "@/logic/GroundFade";
import { type Icon3D, IconLayer3D } from "@/logic/IconLayer3D";
import { type Model3D, ModelLayer3D } from "@/logic/ModelLayer3D";
import { type Path3D, PathLayer3D } from "@/logic/PathLayer3D";
import { useAppStore } from "@/store/AppStore";

/** The beams' colours in the 3D models (webmap.solids: the hall's beam, the tower's beacon). */
const BEAMS = ["#ff8c1a", "#9fe8ff"];

/** Puts the 3D view's icons on the map (IconLayer3D) while it is tilted, fed from the tiles' icon_rows layer. */
export function Icons3D({ map, geo, info, meta }: { map: MapLibreMap; geo: Geo; info: MapInfo; meta: Meta }) {
	const app = useAppClient();
	const settings = useSettings();
	const tilted = useAppStore((s) => (s.camera?.pitch ?? map.getPitch()) > 1);
	const replayPos = useAppStore((s) => (s.replay ? s.replay.pos : null));
	const selIcon = useAppStore((s) => (s.selected?.kind === "icon" ? s.selected.id : -1));
	const layer = useRef<IconLayer3D | null>(null);
	const on = tilted && settings?.layers.Icons !== false;
	const models = settings?.layers["3D models"] !== false;
	const pathsOn = tilted && settings?.layers.Paths !== false;
	const st = settings?.style;
	const iconStyle = String(st?.icon_style ?? "game art");
	const pathLayer = useRef<PathLayer3D | null>(null);
	const strong = st ? styleColour(st, "path_col", meta.colours.path_multi) : meta.colours.path_multi;
	const weak = st ? styleColour(st, "path_col1", meta.colours.path_single) : meta.colours.path_single;
	const pathStyle = st?.path_style ?? "solid";
	const pathWidth = Number(st?.path_width) || 3;

	// the 3D models, drawn by ModelLayer3D (size, height and render distance applied at once)
	const modelsOn = tilted && models;
	const beams = st?.d3_beams !== false;
	const modelLayer = useRef<ModelLayer3D | null>(null);
	useEffect(() => {
		if (!modelsOn) return;
		const hex = (h: string): [number, number, number] =>
			[1, 3, 5].map((k) => Number.parseInt(h.slice(k, k + 2), 16) / 255) as [number, number, number];
		const l = new ModelLayer3D();
		modelLayer.current = l;
		map.addLayer(l, "bookmarks");
		let timer = 0;
		const gather = () => {
			timer = 0;
			const seen = new Set<string>();
			const out: Model3D[] = [];
			for (const f of map.querySourceFeatures("atlas", { sourceLayer: "solids" })) {
				const p = f.properties ?? {};
				if (!beams && BEAMS.includes(String(p.colour))) continue; // View: beams over halls and towers off
				const g = f.geometry;
				const polys = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
				for (const rings of polys) {
					const first = rings[0]?.[0];
					const key = `${p.ax},${p.ay},${p.base},${p.height},${first?.[0]?.toFixed(6)},${first?.[1]?.toFixed(6)}`;
					if (seen.has(key)) continue; // tiles overlap at their edges
					seen.add(key);
					out.push({
						rings: rings as [number, number][][],
						base: Number(p.base) || 0,
						height: Number(p.height) || 0,
						colour: hex(String(p.colour ?? "#9aa0a8")),
						anchor: geo.toLngLat(Number(p.ax), Number(p.ay)),
						step: typeof p.step === "number" ? p.step : -1,
					});
				}
			}
			l.setModels(out);
		};
		const later = () => {
			if (!timer) timer = window.setTimeout(gather, 100);
		};
		map.on("idle", later);
		gather();
		return () => {
			map.off("idle", later);
			if (timer) clearTimeout(timer);
			if (map.getLayer(l.id)) map.removeLayer(l.id);
			modelLayer.current = null;
		};
	}, [map, geo, modelsOn, beams]);

	// the ground fading into black far off (View: 3D view settings, Ground)
	const groundFar = tilted ? Number(st?.d3_ground_far ?? 2.4) : 0;
	useEffect(() => {
		if (!groundFar) return;
		const fade = new GroundFade(groundFar);
		map.addLayer(fade, "solids");
		return () => {
			if (map.getLayer(fade.id)) map.removeLayer(fade.id);
		};
	}, [map, groundFar]);

	// the paths, as ribbons of one width on screen (PathLayer3D)
	useEffect(() => {
		if (!pathsOn) return;
		const rgb = (h: string): [number, number, number] =>
			[1, 3, 5].map((k) => Number.parseInt(h.slice(k, k + 2), 16) / 255) as [number, number, number];
		const l = new PathLayer3D(info.grid.scale / info.world);
		pathLayer.current = l;
		l.width = pathWidth;
		// dashes in atlas units along the path: their shape stays as the distance changes
		l.dash = pathStyle === "dashed" ? [12, 8] : pathStyle === "dotted" ? [3, 9] : [0, 0];
		map.addLayer(l, "bookmarks");
		let timer = 0;
		const gather = () => {
			timer = 0;
			const out: Path3D[] = [];
			for (const f of map.querySourceFeatures("atlas", { sourceLayer: "paths" })) {
				const p = f.properties ?? {};
				const colour = rgb(p.abyss ? meta.colours.path_abyss : p.strong ? strong : weak);
				const step = typeof p.step === "number" ? p.step : -1;
				const g = f.geometry;
				const lines = g.type === "LineString" ? [g.coordinates] : g.type === "MultiLineString" ? g.coordinates : [];
				const id = Number(p.id);
				for (const pts of lines) out.push({ id, pts: pts as [number, number][], colour, step });
			}
			l.setPaths(out);
		};
		// once the map has settled (every tile that came in while zooming rebuilt all paths: it lagged, user)
		const later = () => {
			if (!timer) timer = window.setTimeout(gather, 100);
		};
		map.on("idle", later);
		gather();
		return () => {
			map.off("idle", later);
			if (timer) clearTimeout(timer);
			if (map.getLayer(l.id)) map.removeLayer(l.id);
			pathLayer.current = null;
		};
	}, [map, info, meta, pathsOn, strong, weak, pathStyle, pathWidth]);

	useEffect(() => {
		if (!on) return;
		const l = new IconLayer3D(info.grid.scale / info.world, async (name) => {
			const r = await map.loadImage(app.spriteUrl(name, iconStyle));
			return r.data as CanvasImageSource;
		});
		layer.current = l;
		map.addLayer(l, "bookmarks");
		let timer = 0;
		const gather = () => {
			timer = 0;
			const seen = new Set<number>();
			const icons: Icon3D[] = [];
			for (const f of map.querySourceFeatures("atlas", { sourceLayer: "icon_rows" })) {
				const p = f.properties ?? {};
				const id = Number(p.id);
				if (seen.has(id) || f.geometry.type !== "Point") continue;
				seen.add(id);
				const [lng, lat] = f.geometry.coordinates as [number, number];
				icons.push({
					lng,
					lat,
					atlas: geo.toAtlas(lng, lat),
					id,
					name: String(p.name),
					slot: Number(p.slot) || 0,
					lift: Number(p.lift) || 0,
					step: typeof p.step === "number" ? p.step : -1,
				});
			}
			void l.setIcons(icons);
		};
		const later = () => {
			if (!timer) timer = window.setTimeout(gather, 100);
		};
		map.on("idle", later);
		gather();
		return () => {
			map.off("idle", later);
			if (timer) clearTimeout(timer);
			if (map.getLayer(l.id)) map.removeLayer(l.id);
			layer.current = null;
		};
	}, [map, app, geo, info, on, iconStyle]);

	// biome-ignore lint/correctness/useExhaustiveDependencies: `on` re-runs it for a newly made layer
	useEffect(() => {
		const l = layer.current;
		if (!l) return;
		l.models = models;
		l.pos = replayPos ?? 1e9;
		if (pathLayer.current) pathLayer.current.pos = replayPos ?? 1e9;
		l.selected = selIcon;
		l.far = Number(st?.d3_icon_far) || 2.5;
		l.sizeScale = Number(st?.d3_icon_size) || 1.5;
		l.liftScale = (Number(st?.d3_model_size) || 1) * (Number(st?.d3_model_height) || 1);
		const ml = modelLayer.current;
		if (ml) {
			ml.size = Number(st?.d3_model_size) || 1;
			ml.height = Number(st?.d3_model_height) || 0.8;
			ml.far = Number(st?.d3_model_far) || 2.4;
			ml.pos = replayPos ?? 1e9;
		}
		const pl = pathLayer.current;
		if (pl) {
			pl.lift = Number(st?.d3_path_lift) || 0;
			pl.far = Number(st?.d3_path_far) || 2.6;
			pl.taper = Number(st?.d3_path_taper ?? 0.2);
			pl.solidPx = Number(st?.d3_solid_px ?? 8);
		}
		map.triggerRepaint();
	}, [map, models, replayPos, on, selIcon, st, pathsOn, modelsOn]);

	return null;
}
