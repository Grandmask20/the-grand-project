// @ts-expect-error gifenc ships no types
import { applyPalette, GIFEncoder, quantize } from "gifenc";
import type { Map as MapLibreMap } from "maplibre-gl";
import { ArrayBufferTarget, Muxer } from "webm-muxer";

/** GIF: frames per second and the most frames (the old window's REPLAY_GIF_FPS / REPLAY_GIF_MAX_FRAMES). */
export const GIF_FPS = 15;
export const GIF_MAX_FRAMES = 450;
export const GIF_WIDTH = 720;
/** Video: frames per second. */
export const VIDEO_FPS = 30;
/** The last frame stays up this long (the old window's GIF end hold). */
export const END_HOLD_MS = 2000;

export type ExportKind = "gif" | "video";

/** A line drawn over each frame, as the old window's export did: when, screenshots and maps so far. */
export interface Overlay {
	text: string;
	colour: string;
}

/**
 * Writes a replay frame by frame into a GIF or a WebM video. Frames are given one at a time with a fixed time each,
 * so the file lasts the replay's length whatever the preview speed or how slowly the map draws (user: recording the
 * screen made the export follow the viewer's speed).
 */
export class ReplayExporter {
	readonly width: number;
	readonly height: number;
	private readonly canvas = document.createElement("canvas");
	private readonly gif: ReturnType<typeof GIFEncoder> | null;
	private readonly target = new ArrayBufferTarget();
	private readonly muxer: Muxer<ArrayBufferTarget> | null;
	private readonly encoder: VideoEncoder | null;
	private frames = 0;
	private error: unknown = null;

	constructor(
		private readonly kind: ExportKind,
		width: number,
		height: number,
		private readonly fps: number,
	) {
		this.width = width - (width % 2);
		this.height = height - (height % 2);
		this.canvas.width = this.width;
		this.canvas.height = this.height;
		this.gif = kind === "gif" ? GIFEncoder() : null;
		if (kind === "video") {
			if (typeof VideoEncoder === "undefined")
				throw new Error("This browser can't write videos (no WebCodecs): use GIF.");
			this.muxer = new Muxer({
				target: this.target,
				video: { codec: "V_VP9", width: this.width, height: this.height, frameRate: fps },
			});
			const muxer = this.muxer;
			this.encoder = new VideoEncoder({
				output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
				error: (e) => {
					this.error = e;
				},
			});
			this.encoder.configure({
				codec: "vp09.00.10.08",
				width: this.width,
				height: this.height,
				bitrate: 8_000_000,
				framerate: fps,
			});
		} else {
			this.muxer = null;
			this.encoder = null;
		}
	}

	/** Draw the map's picture (and the overlay) into the next frame. Call inside the map's "render" event. */
	draw(src: HTMLCanvasElement, overlay: Overlay | null): void {
		const ctx = this.canvas.getContext("2d", { willReadFrequently: this.kind === "gif" });
		if (!ctx) return;
		ctx.fillStyle = "#000";
		ctx.fillRect(0, 0, this.width, this.height);
		// the map view's middle at the export's shape
		const s = Math.max(this.width / src.width, this.height / src.height);
		const w = src.width * s;
		const h = src.height * s;
		ctx.drawImage(src, (this.width - w) / 2, (this.height - h) / 2, w, h);
		if (overlay) {
			const pad = Math.round(this.height / 60) + 4;
			ctx.font = `${Math.max(11, Math.round(this.height / 34))}px system-ui, sans-serif`;
			const tw = ctx.measureText(overlay.text).width;
			const lh = Math.round(this.height / 34) + 8;
			ctx.fillStyle = "rgba(18,18,20,0.85)";
			ctx.fillRect(pad, pad, tw + lh + pad * 2, lh + pad);
			ctx.fillStyle = overlay.colour;
			ctx.beginPath();
			ctx.arc(pad * 2 + lh / 3, pad + (lh + pad) / 2, lh / 4, 0, Math.PI * 2);
			ctx.fill();
			ctx.fillStyle = "#e8e8e8";
			ctx.textBaseline = "middle";
			ctx.fillText(overlay.text, pad * 2 + lh * 0.75, pad + (lh + pad) / 2);
		}
	}

	/** Add the drawn frame; `ms` is how long it stays up. */
	add(ms: number): void {
		if (this.error) throw this.error;
		if (this.gif) {
			const ctx = this.canvas.getContext("2d", { willReadFrequently: true });
			if (!ctx) return;
			const { data } = ctx.getImageData(0, 0, this.width, this.height);
			const palette = quantize(data, 256);
			this.gif.writeFrame(applyPalette(data, palette), this.width, this.height, { palette, delay: Math.round(ms) });
		} else if (this.encoder) {
			const us = Math.round(1e6 / this.fps);
			const copies = Math.max(1, Math.round(ms / (1000 / this.fps)));
			for (let i = 0; i < copies; i++) {
				const frame = new VideoFrame(this.canvas, { timestamp: this.frames * us, duration: us });
				this.encoder.encode(frame, { keyFrame: this.frames % (this.fps * 2) === 0 });
				frame.close();
				this.frames++;
			}
			return;
		}
		this.frames++;
	}

	/** Finish the file. */
	async finish(): Promise<Blob> {
		if (this.gif) {
			this.gif.finish();
			return new Blob([this.gif.bytes()], { type: "image/gif" });
		}
		if (!this.encoder || !this.muxer) throw new Error("nothing to finish");
		await this.encoder.flush();
		if (this.error) throw this.error;
		this.muxer.finalize();
		return new Blob([this.target.buffer], { type: "video/webm" });
	}

	/** Drop the export (the encoder's resources). */
	close(): void {
		if (this.encoder && this.encoder.state !== "closed") this.encoder.close();
	}
}

/** Wait until the map has drawn everything for its current view (or `ms` passes). */
export function mapIdle(map: MapLibreMap, ms = 4000): Promise<void> {
	return new Promise((resolve) => {
		const t = setTimeout(resolve, ms);
		map.once("idle", () => {
			clearTimeout(t);
			resolve();
		});
		map.triggerRepaint();
	});
}

/** Run `draw` with the map's canvas inside its next "render" event (its picture can only be copied then). */
export function onNextRender(map: MapLibreMap, draw: (canvas: HTMLCanvasElement) => void): Promise<void> {
	return new Promise((resolve) => {
		map.once("render", () => {
			draw(map.getCanvas());
			resolve();
		});
		map.triggerRepaint();
	});
}

/** Let React and the map catch up with a change (the replay position): two animation frames. */
export function nextFrames(): Promise<void> {
	return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
}
