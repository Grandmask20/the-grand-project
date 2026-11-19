import type { Frames } from "@/domain/replay/Frames";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";
import { revealed } from "@/logic/Replay";

/** "Colour by" as the old window drew it. */
export type TintMode = "by session" | "oldest to newest" | "times seen";

/** Cells on the tint picture's long side: sharp edges at rest (1024 left blocky, soft edges: user), coarser while
 * the replay plays so each step stays quick. */
export const TINT_RES = 2048;
export const TINT_RES_REPLAY = 1024;
/** How strongly "times seen" tints the map (the heat picture's old strength). */
export const HEAT_ALPHA = 0.38;

/** The tint picture's place: a grid over a box around every screenshot. */
export interface TintBox {
	x0: number;
	y0: number;
	cell: number;
	w: number;
	h: number;
}

export const isTintMode = (mode: unknown): mode is TintMode =>
	mode === "by session" || mode === "oldest to newest" || mode === "times seen";

/** The grid around every screenshot (null with none). */
export function tintBox(frames: Frames, replaying: boolean): TintBox | null {
	let [x0, y0, x1, y1] = [Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY, -Infinity, -Infinity];
	for (const fr of frames.frames)
		for (const [x, y] of fr.corners) {
			x0 = Math.min(x0, x);
			y0 = Math.min(y0, y);
			x1 = Math.max(x1, x);
			y1 = Math.max(y1, y);
		}
	if (!(x1 > x0 && y1 > y0)) return null;
	const cell = Math.max(x1 - x0, y1 - y0) / (replaying ? TINT_RES_REPLAY : TINT_RES);
	return { x0, y0, cell, w: Math.ceil((x1 - x0) / cell), h: Math.ceil((y1 - y0) / cell) };
}

const hex = (h: string) => [1, 3, 5].map((k) => Number.parseInt(h.slice(k, k + 2), 16));

/**
 * Paint the tint into RGBA pixels (box.w x box.h). Each spot takes the colour of the newest screenshot over it (by
 * session, or oldest to newest), or of how many screenshots show it (times seen): one flat tint, not translucent shapes
 * per screenshot stacked up where they overlap (user: a bright quilt, unlike the old window). Filled by hand with hard
 * edges: the canvas's own soft shape edges added up where hundreds of screenshot edges cross, and left dotted lines
 * across the map (user). Only where `mask` shows ground (the black fog at the screenshots' edges stays untinted), and
 * while replaying only the screenshots revealed at `pos`.
 */
export function paintTint(
	out: Uint8ClampedArray,
	box: TintBox,
	frames: Frames,
	mode: TintMode,
	plan: ReplayPlan | null,
	pos: number,
	mask: Uint8Array | null,
): void {
	const W = box.w;
	const H = box.h;
	const cover = (corners: [number, number][], paint: (k: number) => void) => {
		const pts = corners.map(([x, y]) => [(x - box.x0) / box.cell, (y - box.y0) / box.cell]);
		let area = 0;
		for (let k = 0; k < pts.length; k++) {
			const [ax, ay] = pts[k];
			const [bx, by] = pts[(k + 1) % pts.length];
			area += ax * by - bx * ay;
		}
		const sgn = area >= 0 ? 1 : -1;
		const xs = pts.map((q) => q[0]);
		const ys = pts.map((q) => q[1]);
		const xa = Math.max(0, Math.floor(Math.min(...xs)));
		const xb = Math.min(W - 1, Math.ceil(Math.max(...xs)));
		const ya = Math.max(0, Math.floor(Math.min(...ys)));
		const yb = Math.min(H - 1, Math.ceil(Math.max(...ys)));
		for (let y = ya; y <= yb; y++)
			for (let x = xa; x <= xb; x++) {
				const px = x + 0.5;
				const py = y + 0.5;
				let inside = true;
				for (let k = 0; k < pts.length && inside; k++) {
					const [ax, ay] = pts[k];
					const [bx, by] = pts[(k + 1) % pts.length];
					if (sgn * ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) < 0) inside = false;
				}
				if (inside && (!mask || mask[y * W + x])) paint(y * W + x);
			}
	};
	const put = (k: number, [r, g, b]: number[]) => {
		out[4 * k] = r;
		out[4 * k + 1] = g;
		out[4 * k + 2] = b;
		out[4 * k + 3] = 255;
	};
	if (mode === "times seen") {
		// each screenshot adds 1 to the spots it covers, then the count picks the colour
		const count = new Uint16Array(W * H);
		for (const i of frames.order)
			if (frames.frames[i].corners.length && revealed(plan, i, pos))
				cover(frames.frames[i].corners, (k) => {
					count[k]++;
				});
		const top = Math.max(1, frames.heat_top);
		const rgb = frames.ramp.map(hex);
		for (let k = 0; k < count.length; k++) {
			const n = count[k];
			if (n) put(k, rgb[Math.min(rgb.length - 1, Math.round(((n - 1) / Math.max(1, top - 1)) * (rgb.length - 1)))]);
		}
		return;
	}
	// oldest first: the newest screenshot over a spot gives its colour
	for (const i of frames.order) {
		const fr = frames.frames[i];
		if (!fr.corners.length || !revealed(plan, i, pos)) continue;
		const colour = hex(
			mode === "by session"
				? frames.sessions[fr.session % frames.sessions.length]
				: frames.ramp[Math.min(frames.ramp.length - 1, Math.max(0, Math.round(fr.rank * (frames.ramp.length - 1))))],
		);
		cover(fr.corners, (k) => put(k, colour));
	}
}
