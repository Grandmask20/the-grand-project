// @ts-expect-error gifenc ships no types
import { applyPalette, GIFEncoder, quantize } from "gifenc";
import type { Map as MapLibreMap } from "maplibre-gl";

/** Frames per second of an exported GIF, and the most frames it holds (the old window's 15 fps / 450 frames). */
export const GIF_FPS = 15;
export const GIF_MAX_FRAMES = 450;
const GIF_WIDTH = 720; // px: a GIF that size stays a few MB; videos are for full size

/**
 * Records the map into an animated GIF while the replay plays (user: the old window exported GIFs, the page only
 * recorded videos). Frames are taken in the map's own "render" event, while its picture is still there to copy.
 */
export class GifRecorder {
	private readonly enc = GIFEncoder();
	private readonly canvas = document.createElement("canvas");
	private last = -1;
	private frames = 0;
	private readonly onRender: () => void;

	constructor(
		private readonly map: MapLibreMap,
		seconds: number,
	) {
		const src = map.getCanvas();
		const w = Math.min(GIF_WIDTH, src.width);
		this.canvas.width = w;
		this.canvas.height = Math.round((src.height / src.width) * w);
		// a long replay is sampled more sparsely so it stays under GIF_MAX_FRAMES
		const step = 1000 / Math.min(GIF_FPS, GIF_MAX_FRAMES / Math.max(1, seconds));
		this.onRender = () => {
			const now = performance.now();
			if (this.last >= 0 && now - this.last < step) return;
			this.last = now;
			this.grab(Math.round(step));
		};
		map.on("render", this.onRender);
	}

	private grab(delay: number) {
		if (this.frames >= GIF_MAX_FRAMES) return;
		const ctx = this.canvas.getContext("2d", { willReadFrequently: true });
		if (!ctx) return;
		ctx.drawImage(this.map.getCanvas(), 0, 0, this.canvas.width, this.canvas.height);
		const { data, width, height } = ctx.getImageData(0, 0, this.canvas.width, this.canvas.height);
		const palette = quantize(data, 256);
		this.enc.writeFrame(applyPalette(data, palette), width, height, { palette, delay });
		this.frames++;
	}

	/** Stop and return the GIF file (null when no frame was taken). */
	finish(): Blob | null {
		this.map.off("render", this.onRender);
		if (!this.frames) return null;
		this.enc.finish();
		return new Blob([this.enc.bytes()], { type: "image/gif" });
	}
}
