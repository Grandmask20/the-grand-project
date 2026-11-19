import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";
import { type GeoJSONStoreFeatures, TerraDraw, TerraDrawFreehandMode } from "terra-draw";
import { TerraDrawMapLibreGLAdapter } from "terra-draw-maplibre-gl-adapter";
import { mapAlive, useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import type { Geo, Point } from "@/logic/Geo";
import { slotOf } from "@/logic/map/LayerOrder";

/** The lasso's look: the Biome select button's gold. */
const GOLD = "#c8a45c";

/**
 * Terra Draw on our map.
 *
 * - Only a plain left-button press starts a lasso: Terra Draw takes a drag of any button, and a right-drag or
 *   Ctrl-drag (the map's turn and tilt) started one and closed the open biome menu (CodeRabbit). The press is
 *   refused where it comes in, so Terra Draw never starts the drag; the moves and the release of a left-button
 *   lasso pass as before.
 * - Double-click is the page's own (zoom in, place a screenshot by hand: MapInteraction), and MapLibre's own
 *   double-click zoom stays off: Terra Draw turns it back on when it stops, which zoomed twice.
 */
export class AtlasDrawAdapter extends TerraDrawMapLibreGLAdapter<MapLibreMap> {
	override getLngLatFromEvent(event: PointerEvent | MouseEvent) {
		if (event.type === "pointerdown" && (event.button !== 0 || event.ctrlKey))
			return null as unknown as { lng: number; lat: number }; // (Terra Draw's own type allows none: it ignores it)
		return super.getLngLatFromEvent(event);
	}

	override setDoubleClickToZoom(): void {}
}

/** The lasso drawn, in atlas units (its ring, not closed), and the screen point it ended at. */
export function lassoOf(feature: GeoJSONStoreFeatures | undefined, geo: Geo): Point[] | null {
	if (feature?.geometry.type !== "Polygon") return null;
	const ring = feature.geometry.coordinates[0] ?? [];
	return ring.slice(0, -1).map(([lng, lat]) => geo.toAtlas(lng, lat));
}

interface Props {
	/** A new lasso is being drawn (the one before goes). */
	onStart: () => void;
	/** One was drawn: its points in atlas units and where it ended on the screen. */
	onDrawn: (polygon: Point[], at: { x: number; y: number }) => void;
}

/**
 * Drawing the lasso round the maps of a biome (Biome select): held left button, drawn freehand by Terra Draw. The
 * drawn lasso stays on the map until this goes (the biome is picked, or Esc), and a new one replaces it. Mounted while
 * the lasso mode is on.
 */
export function LassoDraw({ onStart, onDrawn }: Props) {
	const map = useMapLibre();
	const { geo } = useMapView();
	const handlers = useRef({ onStart, onDrawn });
	handlers.current = { onStart, onDrawn };

	useEffect(() => {
		// on top of the map, in the lasso's place (LAYER_ORDER)
		const adapter = new AtlasDrawAdapter({ map, renderBelowLayerId: slotOf("lasso"), prefixId: "lasso-draw" });
		const draw = new TerraDraw({
			adapter,
			modes: [
				new TerraDrawFreehandMode({
					drawInteraction: "click-drag", // as before: press, draw, let go
					minDistance: 4, // px between points
					// points near the start are kept: by default none within 40 px of it are, and a small lasso came out
					// as copies of its first point (CodeRabbit)
					preventPointsNearClose: false,
					keyEvents: null, // Esc is the page's (MapInteraction: it leaves the mode)
					styles: { fillColor: GOLD, fillOpacity: 0.12, outlineColor: GOLD, outlineWidth: 2 },
				}),
			],
		});
		let kept: string | number | null = null;
		// a new lasso (its polygon: Terra Draw also makes a point to close it on, which isn't a new lasso)
		const changed = (ids: (string | number)[], type: string) => {
			if (type !== "create") return;
			const lasso = ids.find((id) => draw.getSnapshotFeature(id)?.geometry.type === "Polygon");
			if (lasso === undefined) return;
			const old = kept;
			kept = lasso;
			if (old !== null && old !== lasso && draw.getSnapshotFeature(old)) draw.removeFeatures([old]);
			handlers.current.onStart();
		};
		const finished = (id: string | number) => {
			const points = lassoOf(draw.getSnapshotFeature(id), geo);
			if (!points) return;
			const end = points.at(-1) ?? [0, 0];
			const at = map.project(geo.toLngLat(end[0], end[1]));
			handlers.current.onDrawn(points, { x: at.x, y: at.y });
		};
		draw.on("change", changed);
		draw.on("finish", finished);
		draw.start();
		draw.setMode("freehand");
		return () => {
			draw.off("change", changed);
			draw.off("finish", finished);
			if (!mapAlive(map)) return;
			// a lasso cancelled mid-drag (Esc): Terra Draw turned the map's turning off for it and only turns it back on
			// when the drag ends, which no longer comes (CodeRabbit). As it was before the lasso (MapLibre's own drag pan
			// stays off: MapPan's).
			adapter.setDraggability(true);
			draw.stop();
		};
	}, [map, geo]);

	return null;
}
