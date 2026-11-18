import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import type { Geo } from "@/logic/Geo";
import { EMPTY, setData, setImage } from "@/logic/MapStyle";
import { useAppStore } from "@/store/AppStore";

/** Pictures over the map: the screenshot being placed by hand and the one a question is about ("times seen" is
 * drawn by MapTint). */
export function MapImages({ map, geo }: { map: MapLibreMap; geo: Geo }) {
	const app = useAppClient();
	const mode = useAppStore((s) => s.mode);
	const question = useAppState().data?.questions[0] ?? null;

	const ghost = mode.kind === "ghost" ? mode : null;
	useEffect(() => {
		if (!ghost) {
			setImage(map, "ghost-picture", null, null, "selected");
			setData(map, "ghost-line", { type: "FeatureCollection", features: [] });
			return;
		}
		const [x0, y0, x1, y1] = ghost.ghost.box;
		const [cx, cy] = ghost.centre;
		const box: [number, number, number, number] = [x0 + cx, y0 + cy, x1 + cx, y1 + cy];
		setImage(map, "ghost-picture", app.pictureUrl(ghost.ghost.picture), geo.corners(box), "selected", 0.6);
		setData(map, "ghost-line", {
			type: "Feature",
			geometry: {
				type: "LineString",
				coordinates: geo.ring([
					[box[0], box[1]],
					[box[2], box[1]],
					[box[2], box[3]],
					[box[0], box[3]],
				]),
			},
			properties: {},
		});
	}, [map, geo, app, ghost]);

	const preview = question?.preview ?? null;
	useEffect(() => {
		if (!preview) {
			setImage(map, "preview", null, null, "selected");
			setData(map, "preview-line", EMPTY);
			setData(map, "preview-agree", EMPTY);
			return;
		}
		setImage(map, "preview", app.pictureUrl(preview.picture), geo.corners(preview.box), "selected", 0.65);
		const [x0, y0, x1, y1] = preview.box;
		setData(map, "preview-line", {
			type: "Feature",
			geometry: {
				type: "LineString",
				coordinates: geo.ring([
					[x0, y0],
					[x1, y0],
					[x1, y1],
					[x0, y1],
				]),
			},
			properties: {},
		});
		setData(map, "preview-agree", {
			type: "FeatureCollection",
			features: (preview.agree ?? []).map(([x, y]) => ({
				type: "Feature",
				geometry: { type: "Point", coordinates: geo.toLngLat(x, y) },
				properties: {},
			})),
		});
		// the map snaps to it, clear of the question's dialog over the top of the map (a fixed padding left part of
		// the screenshot under the dialog). Measured once the dialog is laid out.
		const frame = requestAnimationFrame(() => {
			const mapTop = map.getContainer().getBoundingClientRect().top;
			const dialog = document.querySelector('[data-slot="dialog-content"]')?.getBoundingClientRect();
			const top = dialog ? Math.max(40, dialog.bottom - mapTop + 24) : 40;
			// with the placed screenshots nearest to it: what it joins, or how far off a weak match would put it
			const n = preview.near ?? preview.box;
			const all = [Math.min(x0, n[0]), Math.min(y0, n[1]), Math.max(x1, n[2]), Math.max(y1, n[3])];
			map.fitBounds(geo.boundsOf(all[0], all[1], all[2], all[3]), {
				padding: { top, bottom: 40, left: 40, right: 40 },
				maxZoom: map.getMaxZoom() - 1,
			});
		});
		return () => cancelAnimationFrame(frame);
	}, [map, geo, app, preview]);

	return null;
}
