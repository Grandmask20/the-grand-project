import { useCallback, useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { useFog } from "@/hooks/replay/UseFog";
import { useFrames } from "@/hooks/replay/UseFrames";
import { collection, EMPTY, line } from "@/logic/map/Features";
import { fogCells, paintFog } from "@/logic/map/Fog";
import { outlineLayer } from "@/logic/map/OverlayLayers";
import { useAppStore } from "@/store/AppStore";
import { CanvasPicture } from "./CanvasPicture";
import { MapLayer } from "./MapLayer";

/**
 * The timelapse on the map: the ground not revealed yet under fog, and the screenshots coming in outlined.
 *
 * The fog is a picture over the atlas, drawn from the step each spot is revealed at every time the replay moves:
 * smooth (soft-edged when revealing by area), and it hides ground whose tiles came in early (user: bands of polygons
 * snapped in, and unloaded areas showed through when pausing or restarting). Per-item opacity or filters by step made
 * MapLibre redo every feature (13k paths) each frame: the page fell seconds behind and kept going after a pause (user).
 */
export function ReplayFog() {
	const { geo } = useMapView();
	const replay = useAppStore((s) => s.replay);
	// the fog belongs to its plan: the plan's token (a replan with the same kind and count of steps kept the old fog)
	const planKey = replay ? String(replay.plan.token ?? 0) : null;
	const field = useFog(planKey).data?.field ?? null;
	const frames = useFrames(!!replay).data;
	const cells = useMemo(() => (field ? fogCells(field) : null), [field]);

	const pos = replay?.pos ?? null;
	const plan = replay?.plan ?? null;
	const area = plan?.area ?? false;
	const nSteps = plan?.n_steps ?? 1;
	const draw = useCallback(
		(ctx: CanvasRenderingContext2D, w: number, h: number) => {
			if (!field || !cells || pos === null) return;
			const img = ctx.createImageData(w, h);
			paintFog(img.data, cells, field.top, pos, area, nSteps);
			ctx.putImageData(img, 0, 0);
		},
		[field, cells, pos, area, nSteps],
	);

	// every outline is put on the map once with its step (not when revealing by area); only the current step's shows
	const outlines = useMemo(() => {
		if (!plan || !frames || plan.area) return EMPTY;
		const features: GeoJSON.Feature[] = [];
		plan.step_of.forEach((s, i) => {
			const f = frames.frames[i];
			if (f?.corners.length) features.push(line(geo.ring(f.corners), { step: s }));
		});
		return collection(features);
	}, [geo, plan, frames]);
	const done = plan ? (pos ?? 0) >= plan.n_steps : true;
	const cur = pos === null ? -1 : Math.ceil(pos - 1e-9) - 1;
	const outline = useMemo(() => outlineLayer(done ? null : cur), [done, cur]);

	return (
		<>
			{replay && field && cells && (
				<CanvasPicture
					id="fog-picture"
					width={field.w}
					height={field.h}
					corners={field.corners}
					draw={draw}
					resampling="linear"
				/>
			)}
			<Source id="outline" type="geojson" data={outlines}>
				<MapLayer spec={outline} />
			</Source>
		</>
	);
}
