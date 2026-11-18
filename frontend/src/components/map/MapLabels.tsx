import type { Map as MapLibreMap, MapGeoJSONFeature } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { Meta } from "@/domain/app/Meta";
import { useSettings } from "@/hooks/app/UseSettings";
import { landmarkColours } from "@/logic/Colours";
import { type PlacedLabel, placeLabels } from "@/logic/Labels";

const ICON_LABEL_ZOOM_PX = 18; // icon names show once an icon is this many px across on screen

/** Names on the map (landmarks, bookmarks, debug marks; icon names zoomed in), drawn as page text over the map so
 * no font server is needed. Labels that would overlap are left out, the most important kept. */
export function MapLabels({ map, meta }: { map: MapLibreMap; meta: Meta }) {
	const settings = useSettings();
	const on = settings?.layers.Labels !== false;
	const [labels, setLabels] = useState<PlacedLabel[]>([]);
	const frame = useRef(0);
	const style = settings?.style;

	useEffect(() => {
		if (!on || !style) {
			setLabels([]);
			return;
		}
		const lm = landmarkColours(meta, style);
		const layout = () => {
			frame.current = 0;
			const canvas = map.getCanvas();
			const w = canvas.clientWidth;
			const h = canvas.clientHeight;
			const want = ["landmarks", "bookmarks", "marks-point", "icons"].filter((id) => {
				if (!map.getLayer(id) || map.getLayoutProperty(id, "visibility") === "none") return false;
				if (id !== "icons") return true;
				const size = map.getLayoutProperty("icons", "icon-size");
				return Array.isArray(size) && iconPx(map) >= ICON_LABEL_ZOOM_PX;
			});
			const feats: MapGeoJSONFeature[] = want.length ? map.queryRenderedFeatures({ layers: want }) : [];
			const seen = new Set<string>();
			const cands = [];
			for (const f of feats) {
				if (f.geometry.type !== "Point") continue;
				const layer = f.layer.id;
				const p = f.properties ?? {};
				const key = `${layer}:${p.id ?? p.label ?? f.id}`;
				if (seen.has(key)) continue;
				seen.add(key);
				const pt = map.project(f.geometry.coordinates as [number, number]);
				if (layer === "landmarks")
					cands.push({ key, x: pt.x, y: pt.y - 18, text: String(p.name ?? p.kind), colour: lm[String(p.kind)] ?? "#ddd", priority: 3 });
				else if (layer === "bookmarks")
					cands.push({ key, x: pt.x, y: pt.y - 14, text: `★ ${p.name}`, colour: meta.colours.bookmark, priority: 4 });
				else if (layer === "marks-point")
					cands.push({ key, x: pt.x, y: pt.y - 8, text: String(p.label), colour: "#ff66ff", priority: 5 });
				else cands.push({ key, x: pt.x, y: pt.y - 12, text: String(p.label), colour: "#e8e8e8", priority: 1 });
			}
			setLabels(placeLabels(cands, w, h));
		};
		const schedule = () => {
			if (!frame.current) frame.current = requestAnimationFrame(layout);
		};
		map.on("moveend", schedule);
		map.on("idle", schedule);
		map.on("sourcedata", schedule);
		schedule();
		return () => {
			map.off("moveend", schedule);
			map.off("idle", schedule);
			map.off("sourcedata", schedule);
			if (frame.current) cancelAnimationFrame(frame.current);
			frame.current = 0;
		};
	}, [map, meta, on, style]);

	// hidden while the map moves: they follow it on the next stop
	const [moving, setMoving] = useState(false);
	useEffect(() => {
		const start = () => setMoving(true);
		const stop = () => setMoving(false);
		map.on("movestart", start);
		map.on("moveend", stop);
		return () => {
			map.off("movestart", start);
			map.off("moveend", stop);
		};
	}, [map]);

	if (!on || moving) return null;
	return (
		<div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
			{labels.map((l) => (
				<div key={l.key} className="map-label" style={{ left: l.left, top: l.top, width: l.width, color: l.colour }}>
					{l.text}
				</div>
			))}
		</div>
	);
}

/** How many screen px an icon spans now (from the icons layer's size at this zoom). */
function iconPx(map: MapLibreMap): number {
	const size = map.getLayoutProperty("icons", "icon-size") as unknown[];
	// ["interpolate", ["exponential", 2], ["zoom"], z0, s0, z1, s1]: sprites are 64 px
	const [z0, s0, z1, s1] = size.slice(3) as number[];
	const z = map.getZoom();
	if (z <= z0) return s0 * 64;
	const t = (z - z0) / Math.max(1e-6, z1 - z0);
	return s0 * (s1 / s0) ** t * 64;
}
