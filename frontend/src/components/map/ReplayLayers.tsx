import type { CanvasSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";
import type { Meta } from "@/domain/app/Meta";
import { useFog } from "@/hooks/replay/UseFog";
import { useFrames } from "@/hooks/replay/UseFrames";
import type { Geo } from "@/logic/Geo";
import { EMPTY, setData } from "@/logic/MapStyle";
import { fogCover, fogStep } from "@/logic/Replay";

/** The area sweep's soft edge, as a share of the whole replay (the app's REPLAY_AREA_SOFT). */
const FOG_SOFT = 0.02;

import { useAppStore } from "@/store/AppStore";
import { MapTint } from "./MapTint";

/** The replay on the map: the ground not revealed yet under fog, and the screenshots coming in outlined. */
export function ReplayLayers({ map, geo, meta }: { map: MapLibreMap; geo: Geo; meta: Meta }) {
	const replay = useAppStore((s) => s.replay);
	// the fog belongs to its plan: the plan's token (a replan with the same kind and count of steps kept the old fog)
	const planKey = replay ? String(replay.plan.token ?? 0) : null;
	const fog = useFog(planKey);
	const frames = useFrames(!!replay);

	// the fog: a picture over the atlas, drawn from the step each spot is revealed at, every time the replay moves.
	// Smooth (soft-edged when revealing by area), and it hides ground whose tiles came in early (user: bands of
	// polygons snapped in, and unloaded areas showed through when pausing or restarting)
	const field = replay ? (fog.data?.field ?? null) : null;
	const cells = useMemo(() => {
		if (!field) return null;
		const bin = atob(field.data);
		const out = new Uint16Array(field.w * field.h);
		for (let i = 0; i < out.length; i++) out[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
		return out;
	}, [field]);
	const canvas = useRef<HTMLCanvasElement | null>(null);
	useEffect(() => {
		if (!field || !cells) {
			if (map.getLayer("fog-picture")) map.removeLayer("fog-picture");
			if (map.getSource("fog-picture")) map.removeSource("fog-picture");
			return;
		}
		const c = document.createElement("canvas");
		c.width = field.w;
		c.height = field.h;
		canvas.current = c;
		// a still picture, put on the map again only when it was drawn anew (animated, MapLibre read it every frame,
		// also while paused)
		map.addSource("fog-picture", { type: "canvas", canvas: c, coordinates: field.corners, animate: false });
		map.addLayer(
			{
				id: "fog-picture",
				type: "raster",
				source: "fog-picture",
				paint: { "raster-fade-duration": 0, "raster-resampling": "linear" },
			},
			"bookmarks",
		);
		// over the map's layers, so it hides what isn't revealed yet; the screenshot box above it
		if (map.getLayer("outline")) map.moveLayer("outline", "bookmarks");
		return () => {
			canvas.current = null;
			if (map.getLayer("fog-picture")) map.removeLayer("fog-picture");
			if (map.getSource("fog-picture")) map.removeSource("fog-picture");
		};
	}, [map, field, cells]);

	const pos = replay?.pos ?? null;
	const area = replay?.plan.area ?? false;
	const nSteps = replay?.plan.n_steps ?? 1;
	useEffect(() => {
		const c = canvas.current;
		if (!c || !field || !cells || pos === null) return;
		const ctx = c.getContext("2d");
		if (!ctx) return;
		const img = ctx.createImageData(field.w, field.h);
		const px = img.data;
		const soft = Math.max(1e-6, FOG_SOFT * nSteps); // the sweep's edge fades over this many steps
		for (let i = 0; i < cells.length; i++) {
			const v = cells[i];
			if (v === 65535) continue; // no ground: nothing to hide
			px[4 * i + 3] = Math.round(fogCover(fogStep(v, field.top, area), pos, area, soft) * 255);
		}
		ctx.putImageData(img, 0, 0);
		const src = map.getSource("fog-picture") as CanvasSource | undefined;
		if (src) {
			src.play(); // read for one frame
			requestAnimationFrame(() => src.pause());
		}
	}, [map, field, cells, pos, area, nSteps]);

	// the screenshots of the step coming in, outlined (not when revealing by area): every outline is put on the map
	// once with its step, and only the current step's is shown (by opacity, at once). Setting new outline data on
	// every step was handled in the background and trailed the replay (user).
	const cur = pos === null ? -1 : Math.ceil(pos - 1e-9) - 1;
	const plan = replay?.plan ?? null;
	useEffect(() => {
		if (!plan || !frames.data || plan.area) {
			setData(map, "outline", EMPTY);
			return;
		}
		const features: GeoJSON.Feature[] = [];
		plan.step_of.forEach((s, i) => {
			const f = frames.data?.frames[i];
			if (f?.corners.length)
				features.push({
					type: "Feature",
					geometry: { type: "LineString", coordinates: geo.ring(f.corners) },
					properties: { step: s },
				});
		});
		setData(map, "outline", { type: "FeatureCollection", features });
	}, [map, geo, plan, frames.data]);
	const done = plan ? (pos ?? 0) >= plan.n_steps : true;
	useEffect(() => {
		if (map.getLayer("outline"))
			map.setPaintProperty("outline", "line-opacity", done ? 0 : ["case", ["==", ["get", "step"], cur], 0.9, 0]);
	}, [map, cur, done]);

	return <MapTint map={map} geo={geo} meta={meta} />;
}
