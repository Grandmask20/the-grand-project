import type { MapStyleImageMissingEvent } from "maplibre-gl";
import { useEffect, useRef } from "react";
import nodePicture from "@/assets/map_node_icon.webp";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings } from "@/hooks/app/UseSettings";
import { mapAlive, useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { OWN_IMAGES, squareImage } from "@/logic/map/Pictures";

/**
 * The pictures the map's layers draw: its own (the squares map style, the game's map node picture) and the map
 * content icons'. An icon picture MapLibre asks for is handed out blank at once (styleimagemissing), and the real one
 * replaces it when it has come in (the tiles using it are laid out again: an update in place left the ones on screen
 * with the old picture). Another icon style or art loads every picture again.
 */
export function MapSprites() {
	const map = useMapLibre();
	const app = useAppClient();
	const { info } = useMapView();
	const style = String(useSettings()?.style.icon_style ?? "game art");
	const art = info.sprite.art;
	const S = info.sprite.size;
	const asked = useRef(new Set<string>()); // the pictures MapLibre asked for

	useEffect(() => {
		if (!map.hasImage("node-square")) map.addImage("node-square", squareImage(), { sdf: true });
		if (!map.hasImage("node-square-solid")) map.addImage("node-square-solid", squareImage(true), { sdf: true });
		void map
			.loadImage(nodePicture)
			.then((img) => {
				if (mapAlive(map) && !map.hasImage("node-picture")) map.addImage("node-picture", img.data);
			})
			.catch(() => undefined); // the "map icons" style then draws nothing
	}, [map]);

	// the pictures in the current style replace the blank (or older) ones, several at once: another style or art loads
	// every picture again (the effect anew: the older one's late pictures are dropped by `live`, not by comparing a
	// ref made anew every render, which dropped pictures after any re-render: CodeRabbit)
	useEffect(() => {
		let live = true;
		const fetch = (name: string) => map.loadImage(app.spriteUrl(name, style, art)).then((r) => [name, r.data] as const);
		// replaced, not updated in place: updateImage reached only tiles laid out after it, and the ones on screen kept
		// the older picture, so the map showed the style picked before (user: "lagged behind by 1 step"; a size change,
		// laying the icons out again, put it right). A removed and added picture has MapLibre lay out again the tiles
		// that use it; all of a batch in one go, so that happens once (one by one, a new style took ~6 s to show).
		const put = (pics: (readonly [string, HTMLImageElement | ImageBitmap])[]) => {
			if (!live || !mapAlive(map)) return;
			for (const [name, data] of pics) {
				if (!map.hasImage(name)) continue;
				map.removeImage(name);
				map.addImage(name, data);
			}
		};
		// pictures MapLibre asks for while laying out: gathered for a moment, then put in together
		let waiting: (readonly [string, HTMLImageElement | ImageBitmap])[] = [];
		let timer: ReturnType<typeof setTimeout> | null = null;
		const missing = (e: MapStyleImageMissingEvent) => {
			if (OWN_IMAGES.has(e.id) || map.hasImage(e.id)) return;
			map.addImage(e.id, { width: S, height: S, data: new Uint8Array(S * S * 4) });
			asked.current.add(e.id);
			fetch(e.id)
				.then((pic) => {
					waiting.push(pic);
					timer ??= setTimeout(() => {
						timer = null;
						const batch = waiting;
						waiting = [];
						put(batch);
					}, 50);
				})
				.catch(() => undefined); // no picture: it stays blank
		};
		map.on("styleimagemissing", missing);
		// another style or art: every picture asked for so far, all put in once they have all come
		const names = [...asked.current];
		if (names.length)
			void Promise.allSettled(names.map(fetch)).then((all) =>
				put(all.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []))),
			);
		return () => {
			live = false;
			if (timer) clearTimeout(timer);
			map.off("styleimagemissing", missing);
		};
	}, [map, app, S, style, art]);

	return null;
}
