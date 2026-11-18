import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings } from "@/hooks/app/UseSettings";
import { useTypes } from "@/hooks/find/UseTypes";
import type { Geo } from "@/logic/Geo";
import { useAppStore } from "@/store/AppStore";

const TOWER = "LostTower"; // the tower picture over Tower landmarks (View: Pictures on the map)

/**
 * The map content icons: the game's pictures at their own size on the ground as you zoom (hidden while too small to
 * read). Their pictures are loaded first; the layer goes under the map dots (above them in 3D).
 */
export function MapIcons({ map, geo, info }: { map: MapLibreMap; geo: Geo; info: MapInfo }) {
	const app = useAppClient();
	const types = useTypes();
	const bumpLook = useAppStore((s) => s.bumpLook);
	const settings = useSettings();
	const iconStyle = String(settings?.style.icon_style ?? "game art");
	const iconSize = Number(settings?.style.icon_size) || 1;
	const loadedStyle = useRef(iconStyle);
	const names = useMemo(() => {
		const icons = types.data?.sections.find((s) => s.title === "Map icons")?.rows ?? [];
		return [...new Set([...icons.map((r) => r.icon), TOWER])].sort();
	}, [types.data]);

	useEffect(() => {
		let live = true;
		const sp = info.sprite;
		// another picture style: every picture again (same size: replaced in place)
		const restyle = loadedStyle.current !== iconStyle;
		loadedStyle.current = iconStyle;
		const missing = restyle ? names : names.filter((n) => !map.hasImage(n));
		Promise.all(
			missing.map((n) =>
				map
					.loadImage(app.spriteUrl(n, iconStyle))
					.then((r) => {
						if (!live) return;
						if (map.hasImage(n)) map.updateImage(n, r.data);
						else map.addImage(n, r.data);
					})
					.catch(() => undefined),
			),
		).then(() => {
			if (!live) return;
			// screen px per atlas unit at zoom z is geo.pxPerUnit(z): an icon spans sp.units atlas units
			// icon size times the View tab's setting
			const size = (z: number) => (iconSize * sp.units * geo.pxPerUnit(z)) / sp.size;
			const zMin = Math.min(info.maxzoom - 0.5, geo.zoomFor(sp.min_px / sp.units));
			if (!map.getLayer("icons")) {
				map.addLayer(
					{
						id: "icons",
						type: "symbol",
						source: "atlas",
						"source-layer": "icons",
						minzoom: zMin,
						layout: {
							"icon-image": ["get", "name"],
							"icon-size": [
								"interpolate",
								["exponential", 2],
								["zoom"],
								zMin,
								size(zMin),
								info.maxzoom,
								size(info.maxzoom),
							],
							"icon-allow-overlap": true,
							"icon-ignore-placement": true,
						},
					},
					map.getPitch() > 1 ? "bookmarks" : "maps",
				);
				if (!map.getLayer("icons-3d"))
					map.addLayer(
						{
							id: "icons-3d",
							type: "symbol",
							source: "atlas",
							"source-layer": "icon_rows",
							minzoom: zMin,
							layout: {
								visibility: "none",
								"icon-image": ["get", "name"],
								"icon-size": [
									"interpolate",
									["exponential", 2],
									["zoom"],
									zMin,
									size(zMin),
									info.maxzoom,
									size(info.maxzoom),
								],
								"icon-anchor": "bottom",
								"icon-pitch-alignment": "viewport",
								"icon-rotation-alignment": "viewport",
								// all drawn (leaving overlapping ones out hid the near ones and made them pop: user);
								// MapLibre fades symbols near the horizon itself. The offset is set by applyLook.
								"icon-allow-overlap": true,
								"icon-ignore-placement": true,
								"symbol-z-order": "viewport-y",
							},
						},
						"bookmarks",
					);
				if (!map.getLayer("towers"))
					map.addLayer(
						{
							id: "towers",
							type: "symbol",
							source: "atlas",
							"source-layer": "landmarks",
							filter: ["==", ["get", "kind"], "Tower"],
							minzoom: zMin,
							layout: {
								"icon-image": TOWER,
								"icon-size": [
									"interpolate",
									["exponential", 2],
									["zoom"],
									zMin,
									2 * size(zMin),
									info.maxzoom,
									2 * size(info.maxzoom),
								],
								"icon-allow-overlap": true,
								"icon-ignore-placement": true,
								"icon-anchor": "bottom",
							},
						},
						"bookmarks",
					);
				bumpLook(); // their visibility and the replay's filter
			} else {
				map.setLayoutProperty("icons", "icon-size", [
					"interpolate",
					["exponential", 2],
					["zoom"],
					zMin,
					size(zMin),
					info.maxzoom,
					size(info.maxzoom),
				]);
			}
			if (missing.length && map.getLayer("icons")) {
				map.setLayoutProperty("icons", "icon-image", ["get", "name"]); // laid out again with the new pictures
			}
		});
		return () => {
			live = false;
		};
	}, [map, app, geo, info, names, bumpLook, iconStyle, iconSize]);

	return null;
}
