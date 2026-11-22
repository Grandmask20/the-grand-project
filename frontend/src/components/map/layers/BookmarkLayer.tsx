import { useMemo } from "react";
import { Source } from "react-map-gl/maplibre";
import { useSettings } from "@/hooks/app/UseSettings";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useMapView } from "@/hooks/map/UseMapView";
import { bookmarkLook } from "@/logic/BookmarkLook";
import { layerOn } from "@/logic/map/AtlasLayers";
import { collection, EMPTY, line, point } from "@/logic/map/Features";
import { bookmarkIconLayer, bookmarkLayer, litRouteLayers, savedRouteLayer } from "@/logic/map/OverlayLayers";
import { routeLines } from "@/logic/SavedRoutes";
import { isSymbol, symbolImageId } from "@/logic/Symbols";
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

	// where a pin sits (View: on the icon row above its spot, or on the map node itself) and its size
	const style = settings?.style;
	const up = style?.bookmark_at === "map node" ? 0 : meta.icon_row_dy;
	const size = Number(style?.bookmark_size) || 1;
	const { pins, routes } = useMemo(() => {
		const pins: GeoJSON.Feature[] = [];
		const routes: GeoJSON.Feature[] = [];
		for (const g of bookmarks?.groups ?? [])
			for (const b of g.items) {
				// its look: its own, else its group's (none: the layer's own colour, no icon). A symbol: its picture in
				// that colour, no ring; a map icon's picture in a ring of the colour, unless without one
				const { colour, icon, plain } = bookmarkLook(b, g);
				const symbol = isSymbol(icon);
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
						geometry: { type: "Point", coordinates: geo.toLngLat(b.x, b.y - up) },
						properties: {
							id: b.id,
							name: b.name,
							...(colour && { colour }),
							icon: symbol ? symbolImageId(icon, colour || meta.colours.bookmark) : icon,
							...(icon && { ring: !symbol && !plain }),
						},
					});
			}
		return { pins: collection(pins), routes: collection(routes) };
	}, [geo, bookmarks, meta, up]);
	// saved routes: the Routes button's (on / saved only), not the Bookmarks switch (user: they had no switch)
	const routesOn = (!settings || layerOn(settings, "Saved routes")) && !replaying;
	const specs = useMemo(
		() => [bookmarkLayer(geo, meta, on, size), bookmarkIconLayer(geo, meta, on, size)],
		[geo, meta, on, size],
	);
	const routeSpec = useMemo(() => savedRouteLayer(meta, routesOn), [meta, routesOn]);

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
				<MapLayers specs={specs} />
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
