import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useMapView } from "@/hooks/map/UseMapView";
import { boxLine, EMPTY } from "@/logic/map/Features";
import { ghostLineLayer } from "@/logic/map/OverlayLayers";
import { useAppStore } from "@/store/AppStore";
import { MapLayer } from "./MapLayer";
import { PictureLayer } from "./PictureLayer";

/** The screenshot being placed by hand (File > Place by hand): its picture where it would go, outlined. */
export function GhostLayers() {
	const app = useAppClient();
	const { geo } = useMapView();
	const mode = useAppStore((s) => s.mode);
	const ghost = mode.kind === "ghost" ? mode : null;

	const box = useMemo((): [number, number, number, number] | null => {
		if (!ghost) return null;
		const [x0, y0, x1, y1] = ghost.ghost.box;
		const [cx, cy] = ghost.centre;
		return [x0 + cx, y0 + cy, x1 + cx, y1 + cy];
	}, [ghost]);
	const outline = useMemo(() => (box ? boxLine(geo, box) : EMPTY), [geo, box]);
	const corners = useMemo(() => (box ? geo.corners(box) : null), [geo, box]);

	return (
		<>
			{ghost && corners && (
				<PictureLayer id="ghost-picture" url={app.pictureUrl(ghost.ghost.picture)} corners={corners} opacity={0.6} />
			)}
			<Source id="ghost-line" type="geojson" data={outline}>
				<MapLayer spec={ghostLineLayer()} />
			</Source>
		</>
	);
}
