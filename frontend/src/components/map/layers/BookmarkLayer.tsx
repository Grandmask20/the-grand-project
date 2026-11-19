import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useSettings } from "@/hooks/app/UseSettings";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useMapView } from "@/hooks/map/UseMapView";
import { layerOn } from "@/logic/map/AtlasLayers";
import { collection, EMPTY, line, point } from "@/logic/map/Features";
import { bookmarkLayer, litRouteLayers, savedRouteLayer } from "@/logic/map/OverlayLayers";
import { routeLines } from "@/logic/SavedRoutes";
import { useAppStore } from "@/store/AppStore";
import { MapLayer, MapLayers } from "./MapLayer";

/**
 * The bookmarks, from the page's bookmark list: the ones neither hidden nor in a hidden group. Hiding a group or a
 * bookmark is instant, the vector tiles (every map node and path) aren't made again for it (user: toggling a group
 * was slow on rc1). Not part of how the atlas was made: hidden while replaying (user: they showed from the start).
 */
export function BookmarkLayer() {
	const { geo, meta } = useMapView();
	const bookmarks = useBookmarks().data;
	const settings = useSettings();
	const replaying = useAppStore((s) => s.replay !== null);
	const on = (!settings || layerOn(settings, "Bookmarks")) && !replaying;

	const { pins, routes } = useMemo(() => {
		const pins: GeoJSON.Feature[] = [];
		const routes: GeoJSON.Feature[] = [];
		for (const g of bookmarks?.groups ?? [])
			for (const b of g.items) {
				if (!b.shown) continue;
				// a saved route: its lines, no pin (it isn't a spot)
				if (b.route)
					routes.push(
						...routeLines(b.route).map((l, i) =>
							line(
								l.map(([x, y]) => geo.toLngLat(x, y)),
								{ id: b.id, branch: i > 0 },
							),
						),
					);
				else
					pins.push({
						type: "Feature",
						id: b.id,
						geometry: { type: "Point", coordinates: geo.toLngLat(b.x, b.y) },
						properties: { id: b.id, name: b.name },
					});
			}
		return { pins: collection(pins), routes: collection(routes) };
	}, [geo, bookmarks]);
	const spec = useMemo(() => bookmarkLayer(geo, meta, on), [geo, meta, on]);
	const routeSpec = useMemo(() => savedRouteLayer(meta, on), [meta, on]);

	// the route lit up: clicked in Bookmarks, or its maps being changed (user: it didn't light up as a bookmark
	// does); its maps ringed, branches in their colour
	const litId = useAppStore((s) => (s.mode.kind === "route-edit" ? s.mode.id : s.routeLit));
	const lit = useMemo(() => {
		const r = bookmarks?.groups.flatMap((g) => g.items).find((b) => b.id === litId)?.route;
		if (!r || replaying) return EMPTY;
		const at = ([x, y]: [number, number]) => geo.toLngLat(x, y);
		return collection([
			...routeLines(r).map((l, i) => line(l.map(at), { branch: i > 0 })),
			...(r.legs ?? []).flatMap((l) => l.maps.map((p) => point(at(p)))),
		]);
	}, [geo, bookmarks, litId, replaying]);
	const litSpecs = useMemo(() => litRouteLayers(geo, meta), [geo, meta]);

	return (
		<>
			<Source id="bookmarks" type="geojson" data={pins}>
				<MapLayer spec={spec} />
			</Source>
			<Source id="saved-routes" type="geojson" data={routes}>
				<MapLayer spec={routeSpec} />
			</Source>
			<Source id="route-lit" type="geojson" data={lit}>
				<MapLayers specs={litSpecs} />
			</Source>
		</>
	);
}
