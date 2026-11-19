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
 * The VP9 codec string for a video of this size and frame rate: profile 0, 8-bit, at the lowest level that holds
 * it (level 1.0, always declared before, is for tiny pictures: CodeRabbit).
 */
export function vp9Codec(width: number, height: number, fps: number): string {
	const rate = width * height * fps; // samples per second
	const px = width * height;
	// (level, max picture size, max samples per second) from the VP9 levels table
	const levels: [string, number, number][] = [
		["31", 983040, 36864000],
		["40", 2228224, 83558400],
		["41", 2228224, 160432128],
		["50", 8912896, 311951360],
		["51", 8912896, 588251136],
		["60", 35651584, 1176502272],
	];
	const level = levels.find(([, p, r]) => px <= p && rate <= r)?.[0] ?? "62";
	return `vp09.00.${level}.08`;
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
	private elapsed = 0; // ms of the file so far (a GIF's frame times are whole 10 ms: carried over so the total is right)
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
				codec: vp9Codec(this.width, this.height, fps),
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
			const delay = Math.round((this.elapsed + ms) / 10) * 10 - Math.round(this.elapsed / 10) * 10;
			this.elapsed += ms;
			this.gif.writeFrame(applyPalette(data, palette), this.width, this.height, { palette, delay });
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

/**
 * Wait until the map's tiles for its current view are in (and the timelapse's fog, with `fog`), or `ms` passes. Not the map's "idle" event: the replay's
 * fog picture is redrawn every frame, so the map is never idle and each frame waited the whole timeout.
 */
export function mapIdle(map: MapLibreMap, ms = 3000, fog = false): Promise<void> {
	return new Promise((resolve) => {
		const t0 = performance.now();
		const check = () => {
			// the ground and the map's data: other sources (the fog picture) never count as loaded while animating;
			// with `fog`, the fog picture must be on the map (an export's first frames went out unfogged: CodeRabbit)
			const done =
				["terrain", "atlas"].every((id) => !map.getSource(id) || map.isSourceLoaded(id)) &&
				(!fog || !!map.getSource("fog-picture"));
			if (done || performance.now() - t0 > ms) resolve();
			else setTimeout(check, 30);
		};
		map.triggerRepaint();
		setTimeout(check, 30);
	});
}

/**
 * Run `draw` with the map's canvas inside its next "render" event (its picture can only be copied then). Fails when
 * drawing fails or the map is removed first (an atlas switch): the wait never ended then (CodeRabbit).
 */
export function onNextRender(map: MapLibreMap, draw: (canvas: HTMLCanvasElement) => void): Promise<void> {
	return new Promise((resolve, reject) => {
		const removed = () => {
			map.off("render", rendered);
			reject(new Error("the map was replaced during the export"));
		};
		const rendered = () => {
			map.off("remove", removed);
			try {
				draw(map.getCanvas());
				resolve();
			} catch (e) {
				reject(e);
			}
		};
		map.once("render", rendered);
		map.once("remove", removed);
		map.triggerRepaint();
	});
}

/** Let React and the map catch up with a change (the replay position): two animation frames. */
export function nextFrames(): Promise<void> {
	return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
}
