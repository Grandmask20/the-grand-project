import { useCallback, useEffect } from "react";
import { scenePick, selection3d } from "@/domain/map/Scene3D";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings } from "@/hooks/app/UseSettings";
import { useCustomLayer } from "@/hooks/map/UseCustomLayer";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { useScene3D } from "@/hooks/map/UseScene3D";
import { styleColour } from "@/logic/Colours";
import { GroundFade } from "@/logic/GroundFade";
import { IconLayer3D } from "@/logic/IconLayer3D";
import { ModelLayer3D } from "@/logic/ModelLayer3D";
import { PathLayer3D } from "@/logic/PathLayer3D";
import { useAppStore } from "@/store/AppStore";

/** The beams' colours in the 3D models (webmap.solids: the hall's beam, the tower's beacon). */
const BEAMS = ["#ff8c1a", "#9fe8ff"];

const rgb = (h: string): [number, number, number] =>
	[1, 3, 5].map((k) => Number.parseInt(h.slice(k, k + 2), 16) / 255) as [number, number, number];

/**
 * The 3D view while the map is tilted: models, paths and icons as WebGL layers of our own (ModelLayer3D, PathLayer3D,
 * IconLayer3D), and the ground fading out far off. Their data is the app's 3D scene, whole and once per version
 * (useScene3D): each layer is made while shown, and given its data whenever it or the data changes. Gathered from
 * the tiles on screen after every move before, they lagged, missed what tiles left out zoomed out and doubled at tile
 * edges.
 */
export function Scene3D() {
	const app = useAppClient();
	const map = useMapLibre();
	const { geo, info, meta } = useMapView();
	const settings = useSettings();
	const tilted = useAppStore((s) => (s.camera?.pitch ?? map.getPitch()) > 1);
	const replayPos = useAppStore((s) => (s.replay ? s.replay.pos : null));
	const selected = useAppStore((s) => s.selected);
	const st = settings?.style;
	const layers = settings?.layers;
	const scene = useScene3D(tilted).data;
	const sel = selection3d(selected);
	const iconStyle = String(st?.icon_style ?? "game art");
	const beams = st?.d3_beams !== false;
	const freq = Number(st?.path_freq) || 0;
	const strong = st ? styleColour(st, "path_col", meta.colours.path_multi) : meta.colours.path_multi;
	const weak = st ? styleColour(st, "path_col1", meta.colours.path_single) : meta.colours.path_single;

	// --- the layers, made while they are shown (each its own state: the data effects below follow the layer itself,
	// so a layer made anew, for another map info or icon style, gets the data too: it stayed empty, CodeRabbit)
	const k = info.grid.scale / info.world; // atlas units -> mercator units
	const art = info.sprite.art;
	const makeModels = useCallback(() => new ModelLayer3D(), []);
	const makePaths = useCallback(() => new PathLayer3D(k), [k]);
	const makeIcons = useCallback(
		() =>
			new IconLayer3D(k, async (name) => {
				const r = await map.loadImage(app.spriteUrl(name, iconStyle, art));
				return r.data as CanvasImageSource;
			}),
		[map, app, k, iconStyle, art],
	);
	const modelLayer = useCustomLayer(tilted && layers?.["3D models"] !== false, makeModels);
	const pathLayer = useCustomLayer(tilted && layers?.Paths !== false, makePaths);
	const iconLayer = useCustomLayer(tilted && layers?.Icons !== false, makeIcons);

	// the ground fading into black far off (View: 3D view settings, Ground): over the flat layers, under ours
	const groundFar = tilted ? Number(st?.d3_ground_far ?? 2.4) : 0;
	const makeFade = useCallback(() => new GroundFade(groundFar), [groundFar]);
	useCustomLayer(groundFar > 0, makeFade);

	// --- their data: the scene, when it comes (and what the View tab changes in it)
	useEffect(() => {
		if (!modelLayer || !scene) return;
		modelLayer.setModels(
			scene.models
				.filter((m) => beams || !BEAMS.includes(m.colour)) // View: beams over halls and towers off
				.map((m) => ({
					rings: m.rings.map((r) => r.map(([x, y]) => geo.toLngLat(x, y))),
					base: m.base,
					height: m.height,
					colour: rgb(m.colour),
					anchor: geo.toLngLat(m.ax, m.ay),
					step: m.step,
					pick: scenePick(m.pick),
				})),
		);
	}, [modelLayer, geo, scene, beams]);

	useEffect(() => {
		if (!pathLayer || !scene) return;
		const abyss = rgb(meta.colours.path_abyss);
		const s = rgb(strong);
		const w = rgb(weak);
		pathLayer.setPaths(
			scene.paths
				// "drawn by at least", applied here (the scene holds every path with its share)
				.filter((p) => p.abyss || (p.share ?? 1) >= freq - 1e-9)
				.map((p) => ({
					id: p.id,
					pts: p.pts.map(([x, y]) => geo.toLngLat(x, y)),
					colour: p.abyss ? abyss : p.strong ? s : w,
					step: p.step,
				})),
		);
	}, [pathLayer, geo, meta, scene, strong, weak, freq]);

	useEffect(() => {
		if (!iconLayer || !scene) return;
		void iconLayer.setIcons(
			scene.icons.map(([x, y, id, name, slot, lift, step]) => {
				const [lng, lat] = geo.toLngLat(x, y);
				return { lng, lat, atlas: [x, y] as [number, number], id, name, slot, lift, step };
			}),
		);
	}, [iconLayer, geo, scene]);

	// --- what the View tab and the timelapse change, applied each frame by the shaders
	useEffect(() => {
		const pos = replayPos ?? 1e9;
		if (iconLayer) {
			iconLayer.models = !!modelLayer;
			iconLayer.pos = pos;
			iconLayer.selected = sel.icon;
			iconLayer.far = Number(st?.d3_icon_far) || 2.5;
			iconLayer.sizeScale = Number(st?.d3_icon_size) || 1.5;
			iconLayer.liftScale = (Number(st?.d3_model_size) || 1) * (Number(st?.d3_model_height) || 1);
		}
		if (modelLayer) {
			modelLayer.size = Number(st?.d3_model_size) || 1;
			modelLayer.height = Number(st?.d3_model_height) || 0.8;
			modelLayer.far = Number(st?.d3_model_far) || 2.4;
			modelLayer.pos = pos;
			modelLayer.selected = sel.model;
		}
		if (pathLayer) {
			pathLayer.pos = pos;
			pathLayer.width = Number(st?.path_width) || 3;
			// dashes in atlas units along the path: their shape stays as the distance changes
			pathLayer.dash = st?.path_style === "dashed" ? [12, 8] : st?.path_style === "dotted" ? [3, 9] : [0, 0];
			pathLayer.lift = Number(st?.d3_path_lift) || 0;
			pathLayer.far = Number(st?.d3_path_far) || 2.6;
			pathLayer.taper = Number(st?.d3_path_taper ?? 0.2);
			pathLayer.solidPx = Number(st?.d3_solid_px ?? 8);
		}
		map.triggerRepaint();
	}, [map, replayPos, sel.icon, sel.model, st, iconLayer, pathLayer, modelLayer]);

	return null;
}
