import type { MapGeoJSONFeature } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { useSettings } from "@/hooks/app/UseSettings";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { landmarkColours } from "@/logic/Colours";
import { type PlacedLabel, placeLabels } from "@/logic/Labels";
import { iconPx } from "@/logic/map/Sizes";
import { useAppStore } from "@/store/AppStore";

const ICON_LABEL_ZOOM_PX = 18; // icon names show once an icon is this many px across on screen

/** Names on the map (landmarks, bookmarks, debug marks; icon names zoomed in), drawn as page text over the map so
 * no font server is needed. Labels that would overlap are left out, the most important kept. */
export function MapLabels() {
	const map = useMapLibre();
	const { geo, info, meta } = useMapView();
	const settings = useSettings();
	const on = settings?.layers.Labels !== false;
	const [labels, setLabels] = useState<PlacedLabel[]>([]);
	const [moving, setMoving] = useState(false);
	const frame = useRef(0);
	const placed = useRef<Set<string>>(new Set());
	const style = settings?.style;

	useEffect(() => {
		if (!on || !style) {
			setLabels([]);
			return;
		}
		const lm = landmarkColours(meta, style);
		const layout = () => {
			frame.current = 0;
			// only from a map at rest: a layout made mid-move showed names at old places when you zoomed quickly (user)
			if (map.isMoving()) return;
			const canvas = map.getCanvas();
			const w = canvas.clientWidth;
			const h = canvas.clientHeight;
			const want = ["landmarks", "bookmarks", "marks-point", "icons"].filter((id) => {
				if (!map.getLayer(id) || map.getLayoutProperty(id, "visibility") === "none") return false;
				if (id !== "icons") return true;
				return iconPx(geo, info, map.getZoom(), Number(style.icon_size) || 1) >= ICON_LABEL_ZOOM_PX;
			});
			const feats: MapGeoJSONFeature[] = want.length ? map.queryRenderedFeatures({ layers: want }) : [];
			const seen = new Set<string>();
			const cands = [];
			for (const f of feats) {
				if (f.geometry.type !== "Point") continue;
				const layer = f.layer.id;
				const p = f.properties ?? {};
				// while replaying, items are only see-through until revealed: their names wait too
				const rp = useAppStore.getState().replay;
				if (rp && typeof p.step === "number" && p.step >= rp.pos) continue;
				const key = `${layer}:${p.id ?? p.label ?? f.id}`;
				if (seen.has(key)) continue;
				seen.add(key);
				const pt = map.project(f.geometry.coordinates as [number, number]);
				if (layer === "landmarks")
					cands.push({
						key,
						x: pt.x,
						y: pt.y - 18,
						text: String(p.name ?? p.kind),
						colour: lm[String(p.kind)] ?? "#ddd",
						priority: 3,
					});
				else if (layer === "bookmarks")
					cands.push({ key, x: pt.x, y: pt.y - 14, text: `★ ${p.name}`, colour: meta.colours.bookmark, priority: 4 });
				else if (layer === "marks-point")
					cands.push({ key, x: pt.x, y: pt.y - 8, text: String(p.label), colour: "#ff66ff", priority: 5 });
				else cands.push({ key, x: pt.x, y: pt.y - 12, text: String(p.label), colour: "#e8e8e8", priority: 1 });
			}
			// names shown last time keep their place before others of the same rank, so they don't blink in and out
			for (const c of cands) if (placed.current.has(c.key)) c.priority += 0.5;
			const out = placeLabels(cands, w, h);
			placed.current = new Set(out.map((l) => l.key));
			setLabels(out);
			setMoving(false);
		};
		const schedule = () => {
			if (!frame.current) frame.current = requestAnimationFrame(layout);
		};
		// hidden while the map moves; laid out again when it stops (and once more when its tiles have come in)
		const start = () => setMoving(true);
		map.on("movestart", start);
		map.on("moveend", schedule);
		map.on("idle", schedule);
		schedule();
		return () => {
			map.off("movestart", start);
			map.off("moveend", schedule);
			map.off("idle", schedule);
			if (frame.current) cancelAnimationFrame(frame.current);
			frame.current = 0;
		};
	}, [map, geo, info, meta, on, style]);

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
