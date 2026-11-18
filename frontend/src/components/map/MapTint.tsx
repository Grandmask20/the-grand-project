import type { CanvasSource, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";
import type { Meta } from "@/domain/app/Meta";
import { useSettings } from "@/hooks/app/UseSettings";
import { useFrames } from "@/hooks/replay/UseFrames";
import type { Geo } from "@/logic/Geo";
import { revealed } from "@/logic/Replay";
import { useAppStore } from "@/store/AppStore";

/** Cells on the tint picture's long side: sharp edges at rest (1024 left blocky, soft edges: user), coarser while
 * the replay plays so each step stays quick. */
const TINT_RES = 2048;
const TINT_RES_REPLAY = 1024;
/** How strongly "times seen" tints the map (the heat picture's old strength). */
const HEAT_ALPHA = 0.38;

/**
 * "Colour by" as the old window drew it: one flat tint over the map at one strength. Each spot takes the colour of
 * the newest screenshot over it (by session, or oldest to newest), or of how many screenshots show it (times seen).
 * Drawn in the page as one picture: translucent shapes per screenshot stacked up where screenshots overlap (user: a
 * bright quilt, unlike the old window), and the heat picture was fetched again at every replay step (it blinked).
 * While replaying, only the screenshots revealed so far count.
 */
export function MapTint({ map, geo, meta }: { map: MapLibreMap; geo: Geo; meta: Meta }) {
	const mode = useSettings()?.style.age_tint ?? "off";
	const on = mode === "by session" || mode === "oldest to newest" || mode === "times seen";
	const plan = useAppStore((s) => s.replay?.plan ?? null);
	const frames = useFrames(on || plan !== null);
	const step = useAppStore((s) => (s.replay ? Math.ceil(s.replay.pos) : null));
	const canvas = useRef<HTMLCanvasElement | null>(null);

	// the picture's place: a box around every screenshot
	const replaying = plan !== null;
	const box = useMemo(() => {
		const f = frames.data;
		if (!f) return null;
		let [x0, y0, x1, y1] = [Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY, -Infinity, -Infinity];
		for (const fr of f.frames)
			for (const [x, y] of fr.corners) {
				x0 = Math.min(x0, x);
				y0 = Math.min(y0, y);
				x1 = Math.max(x1, x);
				y1 = Math.max(y1, y);
			}
		if (!(x1 > x0 && y1 > y0)) return null;
		const cell = Math.max(x1 - x0, y1 - y0) / (replaying ? TINT_RES_REPLAY : TINT_RES);
		return { x0, y0, cell, w: Math.ceil((x1 - x0) / cell), h: Math.ceil((y1 - y0) / cell) };
	}, [frames.data, replaying]);

	// the layer: added while Colour by is on, where the old tint layer sits (under the biomes)
	useEffect(() => {
		if (!on || !box) return;
		const c = document.createElement("canvas");
		c.width = box.w;
		c.height = box.h;
		canvas.current = c;
		const { x0, y0, cell, w, h } = box;
		const coordinates = geo.corners([x0, y0, x0 + w * cell, y0 + h * cell]);
		map.addSource("tint-picture", { type: "canvas", canvas: c, coordinates, animate: false });
		map.addLayer(
			{
				id: "tint-picture",
				type: "raster",
				source: "tint-picture",
				paint: { "raster-opacity": mode === "times seen" ? HEAT_ALPHA : meta.tint_alpha, "raster-fade-duration": 0 },
			},
			"biomes",
		);
		return () => {
			canvas.current = null;
			if (map.getLayer("tint-picture")) map.removeLayer("tint-picture");
			if (map.getSource("tint-picture")) map.removeSource("tint-picture");
		};
	}, [map, geo, meta, on, mode, box]);

	// the drawing: again when the colours, the frames or the replay's step change
	useEffect(() => {
		const c = canvas.current;
		const f = frames.data;
		if (!on || !c || !f || !box) return;
		const ctx = c.getContext("2d", { willReadFrequently: mode === "times seen" });
		if (!ctx) return;
		const pos = step ?? Number.POSITIVE_INFINITY;
		ctx.clearRect(0, 0, c.width, c.height);
		const shape = (corners: [number, number][]) => {
			ctx.beginPath();
			corners.forEach(([x, y], k) => {
				const px = (x - box.x0) / box.cell;
				const py = (y - box.y0) / box.cell;
				if (k === 0) ctx.moveTo(px, py);
				else ctx.lineTo(px, py);
			});
			ctx.closePath();
			ctx.fill();
		};
		if (mode === "times seen") {
			// each screenshot adds 1 to the spots it covers (in the red channel), then the count picks the colour
			ctx.globalCompositeOperation = "lighter";
			ctx.fillStyle = "rgb(1,0,0)";
			for (const i of f.order) if (f.frames[i].corners.length && revealed(plan, i, pos)) shape(f.frames[i].corners);
			ctx.globalCompositeOperation = "source-over";
			const img = ctx.getImageData(0, 0, c.width, c.height);
			const px = img.data;
			const top = Math.max(1, f.heat_top);
			const rgb = f.ramp.map((hex) => [1, 3, 5].map((k) => Number.parseInt(hex.slice(k, k + 2), 16)));
			for (let i = 0; i < px.length; i += 4) {
				const n = px[i];
				if (!n) continue;
				const [r, g, b] =
					rgb[Math.min(rgb.length - 1, Math.round(((n - 1) / Math.max(1, top - 1)) * (rgb.length - 1)))];
				px[i] = r;
				px[i + 1] = g;
				px[i + 2] = b;
				px[i + 3] = 255;
			}
			ctx.putImageData(img, 0, 0);
		} else {
			// oldest first: the newest screenshot over a spot gives its colour
			for (const i of f.order) {
				const fr = f.frames[i];
				if (!fr.corners.length || !revealed(plan, i, pos)) continue;
				ctx.fillStyle =
					mode === "by session"
						? f.sessions[fr.session % f.sessions.length]
						: f.ramp[Math.min(f.ramp.length - 1, Math.max(0, Math.round(fr.rank * (f.ramp.length - 1))))];
				shape(fr.corners);
			}
		}
		// a still canvas source is read once: played for a frame so the map takes the new picture
		const src = map.getSource("tint-picture") as CanvasSource | undefined;
		if (src) {
			src.play();
			requestAnimationFrame(() => src.pause());
		}
	}, [map, on, mode, frames.data, box, plan, step]);

	return null;
}
