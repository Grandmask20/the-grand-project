import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings } from "@/hooks/app/UseSettings";
import { useMapView } from "@/hooks/map/UseMapView";
import { useFrames } from "@/hooks/replay/UseFrames";
import { HEAT_ALPHA, isTintMode, paintTint, tintBox } from "@/logic/map/Tint";
import { useAppStore } from "@/store/AppStore";
import { CanvasPicture } from "./CanvasPicture";

/**
 * "Colour by" (View tab): one flat tint over the map at one strength, drawn in the page as one picture (paintTint),
 * under the biomes. The heat picture was fetched again at every replay step before (it blinked). While replaying,
 * only the screenshots revealed so far count.
 */
export function TintPicture() {
	const { geo, meta } = useMapView();
	const app = useAppClient();
	const mode = useSettings()?.style.age_tint;
	const on = isTintMode(mode);
	const plan = useAppStore((s) => s.replay?.plan ?? null);
	const step = useAppStore((s) => (s.replay ? Math.ceil(s.replay.pos) : null));
	const frames = useFrames(on || plan !== null).data;
	const terrainVersion = useAppState().data?.map?.terrain_version ?? 0;
	const replaying = plan !== null;
	const box = useMemo(() => (frames ? tintBox(frames, replaying) : null), [frames, replaying]);

	// where there is ground: the black fog at the screenshots' edges is left untinted (user). Only the current mask is
	// kept while Colour by is off: older map images' and boxes' go (all of them were kept for good: CodeRabbit)
	const queryClient = useQueryClient();
	const groundId = JSON.stringify(["ground", box, terrainVersion]);
	useEffect(() => {
		queryClient.removeQueries({ queryKey: ["ground"], predicate: (q) => JSON.stringify(q.queryKey) !== groundId });
	}, [queryClient, groundId]);
	const ground = useQuery({
		queryKey: ["ground", box, terrainVersion],
		queryFn: () => (box ? app.groundMask(box) : null),
		enabled: on && !!box,
		staleTime: Number.POSITIVE_INFINITY,
		gcTime: Number.POSITIVE_INFINITY, // kept while Colour by is off (its key changes with the map image)
	});
	const mask = ground.data ?? null;
	// drawn once the mask is here: drawn without it first, the tint showed the screenshots' blocky edges over the fog
	// until it came (user); without a mask (none, or it failed) it is drawn as it is
	const waitMask = on && !!box && ground.isPending && ground.fetchStatus === "fetching";

	const draw = useCallback(
		(ctx: CanvasRenderingContext2D, w: number, h: number) => {
			if (!frames || !box || !isTintMode(mode)) return;
			const img = ctx.createImageData(w, h);
			paintTint(img.data, box, frames, mode, plan, step ?? Number.POSITIVE_INFINITY, mask);
			ctx.putImageData(img, 0, 0);
		},
		[frames, box, mode, plan, step, mask],
	);

	if (!on || !box || waitMask) return null;
	return (
		<CanvasPicture
			id="tint-picture"
			width={box.w}
			height={box.h}
			corners={geo.corners([box.x0, box.y0, box.x0 + box.w * box.cell, box.y0 + box.h * box.cell])}
			draw={draw}
			opacity={mode === "times seen" ? HEAT_ALPHA : meta.tint_alpha}
		/>
	);
}
