import { useEffect, useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { boxLine, collection, EMPTY, point } from "@/logic/map/Features";
import { previewLayers } from "@/logic/map/OverlayLayers";
import { MapLayers } from "./MapLayer";
import { PictureLayer } from "./PictureLayer";

/** The screenshot a question is about (its dialog over the map): its picture where it would go, outlined, and the
 * maps it agrees with. The map snaps to it. */
export function QuestionLayers() {
	const app = useAppClient();
	const map = useMapLibre();
	const { geo } = useMapView();
	const preview = useAppState().data?.questions[0]?.preview ?? null;

	const outline = useMemo(() => (preview ? collection([boxLine(geo, preview.box)]) : EMPTY), [geo, preview]);
	const agree = useMemo(
		() => collection((preview?.agree ?? []).map(([x, y]) => point(geo.toLngLat(x, y)))),
		[geo, preview],
	);
	const corners = useMemo(() => (preview ? geo.corners(preview.box) : null), [geo, preview]);
	const specs = useMemo(() => previewLayers(), []);
	const [lineSpec, agreeSpec] = specs;

	// the map snaps to it, clear of the question's dialog over the top of the map (a fixed padding left part of the
	// screenshot under the dialog). Measured once the dialog is laid out.
	useEffect(() => {
		if (!preview) return;
		const frame = requestAnimationFrame(() => {
			const mapTop = map.getContainer().getBoundingClientRect().top;
			const dialog = document.querySelector('[data-slot="dialog-content"]')?.getBoundingClientRect();
			const top = dialog ? Math.max(40, dialog.bottom - mapTop + 24) : 40;
			// with the placed screenshots nearest to it: what it joins, or how far off a weak match would put it
			const [x0, y0, x1, y1] = preview.box;
			const n = preview.near ?? preview.box;
			map.fitBounds(geo.boundsOf(Math.min(x0, n[0]), Math.min(y0, n[1]), Math.max(x1, n[2]), Math.max(y1, n[3])), {
				padding: { top, bottom: 40, left: 40, right: 40 },
				maxZoom: map.getMaxZoom() - 1,
			});
		});
		return () => cancelAnimationFrame(frame);
	}, [map, geo, preview]);

	return (
		<>
			{preview && corners && (
				<PictureLayer id="preview" url={app.pictureUrl(preview.picture)} corners={corners} opacity={0.65} />
			)}
			<Source id="preview-line" type="geojson" data={outline}>
				<MapLayers specs={[lineSpec]} />
			</Source>
			<Source id="preview-agree" type="geojson" data={agree}>
				<MapLayers specs={[agreeSpec]} />
			</Source>
		</>
	);
}
