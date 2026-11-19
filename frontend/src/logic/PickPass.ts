import type { Map as MapLibreMap } from "maplibre-gl";

type GL = WebGLRenderingContext | WebGL2RenderingContext;

/** A click on a 3D layer, waiting for the next frame to be read back. */
interface PickRequest<T> {
	x: number;
	y: number;
	done: (answer: T) => void;
}

/**
 * The clicks waiting on one 3D layer's next frame. Every click gets an answer: a second click before the frame
 * joins the first instead of replacing it, and a layer that empties or is removed answers "nothing" (a replaced or
 * dropped click never finished, so its handler waited forever: CodeRabbit).
 */
export class PickQueue<T> {
	private waiting: PickRequest<T>[] = [];

	constructor(private readonly none: T) {}

	/** Ask what is drawn at screen (x, y) css px; `ready`: the layer has something drawn. */
	ask(map: MapLibreMap | null, ready: boolean, x: number, y: number): Promise<T> {
		if (!map || !ready) return Promise.resolve(this.none);
		return new Promise((done) => {
			this.waiting.push({ x, y, done });
			map.triggerRepaint();
		});
	}

	get pending(): boolean {
		return this.waiting.length > 0;
	}

	/** The clicks to answer now (the queue is emptied). */
	take(): PickRequest<T>[] {
		const w = this.waiting;
		this.waiting = [];
		return w;
	}

	/** Answer every waiting click with "nothing" (the layer emptied or went away). */
	settle(): void {
		for (const r of this.take()) r.done(this.none);
	}
}

/** The drawing-buffer pixel under screen (x, y) css px: floored and kept inside the buffer (rounded, a click at
 * the top edge read the row above the picture: CodeRabbit). */
export function pickPixel(gl: GL, map: MapLibreMap, x: number, y: number): { px: number; py: number; ratio: number } {
	const W = gl.drawingBufferWidth;
	const H = gl.drawingBufferHeight;
	const ratio = W / Math.max(1, map.getCanvas().clientWidth);
	const px = Math.min(W - 1, Math.max(0, Math.floor(x * ratio)));
	const py = Math.min(H - 1, Math.max(0, H - 1 - Math.floor(y * ratio)));
	return { px, py, ratio };
}

/** The box of drawing-buffer pixels within `r` of (px, py), cut to the buffer (it reached past it at the edges). */
export function pickBox(gl: GL, px: number, py: number, r: number): { x0: number; y0: number; w: number; h: number } {
	const x0 = Math.max(0, px - r);
	const y0 = Math.max(0, py - r);
	const x1 = Math.min(gl.drawingBufferWidth - 1, px + r);
	const y1 = Math.min(gl.drawingBufferHeight - 1, py + r);
	return { x0, y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
}

/**
 * Draw pick colours (`draw`) into a box of the frame being drawn, tested against its depth, and read them back. The
 * frame's own pixels there are put back after, so no pick colour is ever shown or exported (a few pixels of them
 * stayed in the frame on screen until the next one, and in a timelapse export: CodeRabbit). WebGL's scissor, clear
 * colour, depth writes and blending are left as they were.
 *
 * Returns:
 *   The box's pick colours, RGBA rows from the bottom.
 */
export function readPickBox(gl: GL, x0: number, y0: number, w: number, h: number, draw: () => void): Uint8Array {
	const before = new Uint8Array(w * h * 4);
	gl.readPixels(x0, y0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, before);
	const scissor = gl.isEnabled(gl.SCISSOR_TEST);
	const box = gl.getParameter(gl.SCISSOR_BOX) as Int32Array;
	const clear = gl.getParameter(gl.COLOR_CLEAR_VALUE) as Float32Array;
	const depthMask = gl.getParameter(gl.DEPTH_WRITEMASK) as boolean;
	const blend = gl.isEnabled(gl.BLEND);
	gl.enable(gl.SCISSOR_TEST);
	gl.scissor(x0, y0, w, h);
	gl.clearColor(0, 0, 0, 0);
	gl.clear(gl.COLOR_BUFFER_BIT); // colour only: the frame's depth decides what is in front
	gl.depthMask(false);
	gl.disable(gl.BLEND);
	draw();
	const out = new Uint8Array(w * h * 4);
	gl.readPixels(x0, y0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, out);
	// the frame's pixels back: one scissored clear per run of one colour along a row
	for (let j = 0; j < h; j++) {
		let i = 0;
		while (i < w) {
			const k = 4 * (j * w + i);
			let n = 1;
			while (
				i + n < w &&
				before[k + 4 * n] === before[k] &&
				before[k + 4 * n + 1] === before[k + 1] &&
				before[k + 4 * n + 2] === before[k + 2] &&
				before[k + 4 * n + 3] === before[k + 3]
			)
				n++;
			gl.scissor(x0 + i, y0 + j, n, 1);
			gl.clearColor(before[k] / 255, before[k + 1] / 255, before[k + 2] / 255, before[k + 3] / 255);
			gl.clear(gl.COLOR_BUFFER_BIT);
			i += n;
		}
	}
	if (!scissor) gl.disable(gl.SCISSOR_TEST);
	gl.scissor(box[0], box[1], box[2], box[3]);
	gl.clearColor(clear[0], clear[1], clear[2], clear[3]);
	gl.depthMask(depthMask);
	if (blend) gl.enable(gl.BLEND);
	return out;
}

/** The pick code in a pick picture's pixel at byte offset k (0: nothing drawn there). */
export const pickColour = (px: Uint8Array, k: number) => (px[k + 3] ? px[k] + px[k + 1] * 256 + px[k + 2] * 65536 : 0);

/** GLSL (vertex shader, which is highp): a number 0..2^24-1 as three colour bytes, 0..1 each. The fragment shader
 * may be mediump, 16 bits on some GPUs: ids past 2048 came out wrong there (CodeRabbit). */
export const GLSL_CODE_BYTES = `
vec3 codeBytes(float code) {
	return vec3(mod(code, 256.0), mod(floor(code / 256.0), 256.0), floor(code / 65536.0)) / 255.0;
}`;
