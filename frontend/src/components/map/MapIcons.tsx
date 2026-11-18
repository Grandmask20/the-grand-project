import type { Map as MapLibreMap, MapStyleImageMissingEvent } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings } from "@/hooks/app/UseSettings";
import type { Geo } from "@/logic/Geo";
import { iconSize, OWN_IMAGES } from "@/logic/MapStyle";

/**
 * The map content icons' pictures. The icon layers are in the map's style from the start (MapStyle); a picture
 * MapLibre asks for is handed out blank at once (styleimagemissing), and the real one replaces it in place when it has
 * come in, so nothing is laid out again. Before, the layers were added once every picture had loaded, the look applied
 * again after them, and the icons made to lay out anew whenever pictures arrived.
 */
export function MapIcons({ map, geo, info }: { map: MapLibreMap; geo: Geo; info: MapInfo }) {
	const app = useAppClient();
	const settings = useSettings();
	const style = String(settings?.style.icon_style ?? "game art");
	const scale = Number(settings?.style.icon_size) || 1;
	const art = info.sprite.art;
	const S = info.sprite.size;
	const asked = useRef(new Set<string>()); // the pictures MapLibre asked for

	// the picture of `name` in the current style, into the blank (or older) one; another style or art loads every
	// picture again (the effect anew: the older one's late pictures are dropped by `live`, not by comparing a ref
	// made anew every render, which dropped pictures after any re-render: CodeRabbit)
	useEffect(() => {
		let live = true;
		const load = (name: string) => {
			void map
				.loadImage(app.spriteUrl(name, style, art))
				.then((r) => {
					if (!live || !map.hasImage(name)) return;
					map.updateImage(name, r.data);
				})
				.catch(() => undefined); // no picture: it stays blank
		};
		const missing = (e: MapStyleImageMissingEvent) => {
			if (OWN_IMAGES.has(e.id) || map.hasImage(e.id)) return;
			map.addImage(e.id, { width: S, height: S, data: new Uint8Array(S * S * 4) });
			asked.current.add(e.id);
			load(e.id);
		};
		map.on("styleimagemissing", missing);
		for (const name of asked.current) load(name); // another style or art: every picture again, in place
		return () => {
			live = false;
			map.off("styleimagemissing", missing);
		};
	}, [map, app, S, style, art]);

	// their size times the View tab's setting
	useEffect(() => {
		const size = iconSize(geo, info, scale);
		if (map.getLayer("icons")) map.setLayoutProperty("icons", "icon-size", size);
		if (map.getLayer("towers")) map.setLayoutProperty("towers", "icon-size", iconSize(geo, info, 2 * scale)); // the tower picture: twice
	}, [map, geo, info, scale]);

	return null;
}
