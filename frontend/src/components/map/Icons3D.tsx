import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { Meta } from "@/domain/app/Meta";
import type { MapInfo } from "@/domain/map/MapInfo";
import { selection3d } from "@/domain/map/Scene3D";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings } from "@/hooks/app/UseSettings";
import { useScene3D } from "@/hooks/map/UseScene3D";
import { styleColour } from "@/logic/Colours";
import type { Geo } from "@/logic/Geo";
import { GroundFade } from "@/logic/GroundFade";
import { IconLayer3D } from "@/logic/IconLayer3D";
import { ModelLayer3D } from "@/logic/ModelLayer3D";
import { PathLayer3D } from "@/logic/PathLayer3D";
import { pickCode } from "@/logic/Pick";
import { useAppStore } from "@/store/AppStore";

/** The beams' colours in the 3D models (webmap.solids: the hall's beam, the tower's beacon). */
const BEAMS = ["#ff8c1a", "#9fe8ff"];

/** Our 3D layers, bottom to top (each goes in under the bookmarks). */
const LAYERS_3D = ["models-3d-gl", "paths-3d-gl", "icons-3d-gl"];

const rgb = (h: string): [number, number, number] =>
	[1, 3, 5].map((k) => Number.parseInt(h.slice(k, k + 2), 16) / 255) as [number, number, number];

/**
 * The 3D view while the map is tilted: models, paths and icons as WebGL layers of our own (ModelLayer3D, PathLayer3D,
 * IconLayer3D), and the ground fading out far off. Their data is the app's 3D scene, whole and once per version
 * (useScene3D): each layer is made once and given its data when it comes. Gathered from the tiles on screen after
 * every move before, they lagged, missed what tiles left out zoomed out and doubled at tile edges.
 */
export function Icons3D({ map, geo, info, meta }: { map: MapLibreMap; geo: Geo; info: MapInfo; meta: Meta }) {
	const app = useAppClient();
	const settings = useSettings();
	const tilted = useAppStore((s) => (s.camera?.pitch ?? map.getPitch()) > 1);
	const replayPos = useAppStore((s) => (s.replay ? s.replay.pos : null));
	const selected = useAppStore((s) => s.selected);
	const st = settings?.style;
	const layers = settings?.layers;
	const iconsOn = tilted && layers?.Icons !== false;
	const pathsOn = tilted && layers?.Paths !== false;
	const modelsOn = tilted && layers?.["3D models"] !== false;
	const scene = useScene3D(tilted).data;
	const sel = selection3d(selected);
	const iconStyle = String(st?.icon_style ?? "game art");
	const beams = st?.d3_beams !== false;
	const strong = st ? styleColour(st, "path_col", meta.colours.path_multi) : meta.colours.path_multi;
	const weak = st ? styleColour(st, "path_col1", meta.colours.path_single) : meta.colours.path_single;

	const modelLayer = useRef<ModelLayer3D | null>(null);
	const pathLayer = useRef<PathLayer3D | null>(null);
	const iconLayer = useRef<IconLayer3D | null>(null);

	// --- the layers, made while they are shown
	useEffect(() => {
		if (!modelsOn) return;
		const l = new ModelLayer3D();
		modelLayer.current = l;
		map.addLayer(l, "bookmarks");
		return () => {
			if (map.getLayer(l.id)) map.removeLayer(l.id);
			modelLayer.current = null;
		};
	}, [map, modelsOn]);

	useEffect(() => {
		if (!pathsOn) return;
		const l = new PathLayer3D(info.grid.scale / info.world);
		pathLayer.current = l;
		map.addLayer(l, "bookmarks");
		return () => {
			if (map.getLayer(l.id)) map.removeLayer(l.id);
			pathLayer.current = null;
		};
	}, [map, info, pathsOn]);

	useEffect(() => {
		if (!iconsOn) return;
		const l = new IconLayer3D(info.grid.scale / info.world, async (name) => {
			const r = await map.loadImage(app.spriteUrl(name, iconStyle, info.sprite.art));
			return r.data as CanvasImageSource;
		});
		iconLayer.current = l;
		map.addLayer(l, "bookmarks");
		return () => {
			if (map.getLayer(l.id)) map.removeLayer(l.id);
			iconLayer.current = null;
		};
	}, [map, app, info, iconsOn, iconStyle]);

	// the ground fading into black far off (View: 3D view settings, Ground): over the flat layers, under ours
	const groundFar = tilted ? Number(st?.d3_ground_far ?? 2.4) : 0;
	useEffect(() => {
		if (!groundFar) return;
		const fade = new GroundFade(groundFar);
		map.addLayer(fade, LAYERS_3D.find((id) => map.getLayer(id)) ?? "bookmarks");
		return () => {
			if (map.getLayer(fade.id)) map.removeLayer(fade.id);
		};
	}, [map, groundFar]);

	// --- their data: the scene, when it comes (and what the View tab changes in it)
	// biome-ignore lint/correctness/useExhaustiveDependencies: modelsOn: a newly made layer gets the data too
	useEffect(() => {
		const l = modelLayer.current;
		if (!l || !scene) return;
		l.setModels(
			scene.models
				.filter((m) => beams || !BEAMS.includes(m.colour)) // View: beams over halls and towers off
				.map((m) => {
					const [kind, id] = m.pick.split(":");
					return {
						rings: m.rings.map((r) => r.map(([x, y]) => geo.toLngLat(x, y))),
						base: m.base,
						height: m.height,
						colour: rgb(m.colour),
						anchor: geo.toLngLat(m.ax, m.ay),
						step: m.step,
						pick: kind === "node" || kind === "landmark" ? pickCode(kind, Number(id)) : 0,
					};
				}),
		);
	}, [geo, scene, beams, modelsOn]);

	// biome-ignore lint/correctness/useExhaustiveDependencies: pathsOn: a newly made layer gets the data too
	useEffect(() => {
		const l = pathLayer.current;
		if (!l || !scene) return;
		const abyss = rgb(meta.colours.path_abyss);
		const s = rgb(strong);
		const w = rgb(weak);
		l.setPaths(
			scene.paths.map((p) => ({
				id: p.id,
				pts: p.pts.map(([x, y]) => geo.toLngLat(x, y)),
				colour: p.abyss ? abyss : p.strong ? s : w,
				step: p.step,
			})),
		);
	}, [geo, meta, scene, strong, weak, pathsOn]);

	// biome-ignore lint/correctness/useExhaustiveDependencies: iconsOn / iconStyle: a newly made layer gets the data
	useEffect(() => {
		const l = iconLayer.current;
		if (!l || !scene) return;
		void l.setIcons(
			scene.icons.map(([x, y, id, name, slot, lift, step]) => {
				const [lng, lat] = geo.toLngLat(x, y);
				return { lng, lat, atlas: [x, y] as [number, number], id, name, slot, lift, step };
			}),
		);
	}, [geo, scene, iconsOn, iconStyle]);

	// --- what the View tab and the timelapse change, applied each frame by the shaders
	// biome-ignore lint/correctness/useExhaustiveDependencies: the *On flags: newly made layers get them too
	useEffect(() => {
		const pos = replayPos ?? 1e9;
		const il = iconLayer.current;
		if (il) {
			il.models = modelsOn;
			il.pos = pos;
			il.selected = sel.icon;
			il.far = Number(st?.d3_icon_far) || 2.5;
			il.sizeScale = Number(st?.d3_icon_size) || 1.5;
			il.liftScale = (Number(st?.d3_model_size) || 1) * (Number(st?.d3_model_height) || 1);
		}
		const ml = modelLayer.current;
		if (ml) {
			ml.size = Number(st?.d3_model_size) || 1;
			ml.height = Number(st?.d3_model_height) || 0.8;
			ml.far = Number(st?.d3_model_far) || 2.4;
			ml.pos = pos;
			ml.selected = sel.model;
		}
		const pl = pathLayer.current;
		if (pl) {
			pl.pos = pos;
			pl.width = Number(st?.path_width) || 3;
			// dashes in atlas units along the path: their shape stays as the distance changes
			pl.dash = st?.path_style === "dashed" ? [12, 8] : st?.path_style === "dotted" ? [3, 9] : [0, 0];
			pl.lift = Number(st?.d3_path_lift) || 0;
			pl.far = Number(st?.d3_path_far) || 2.6;
			pl.taper = Number(st?.d3_path_taper ?? 0.2);
			pl.solidPx = Number(st?.d3_solid_px ?? 8);
		}
		map.triggerRepaint();
	}, [map, replayPos, sel.icon, sel.model, st, iconsOn, pathsOn, modelsOn]);

	return null;
}
