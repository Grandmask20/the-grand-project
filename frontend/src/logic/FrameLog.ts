/** Records how long the map takes to draw (the old window's frame log): one row per frame, saved as CSV. */
export class FrameLog {
	private rows: [number, number, number, string][] = [];
	private last = 0;
	private readonly start = performance.now();

	/** Note one drawn frame (call from the map's "render" event). */
	frame(zoom: number, what = ""): void {
		const now = performance.now();
		const dt = this.last ? now - this.last : 0;
		this.last = now;
		this.rows.push([Math.round(now - this.start), Math.round(dt * 10) / 10, Math.round(zoom * 100) / 100, what]);
		if (this.rows.length > 100_000) this.rows = this.rows.slice(-50_000);
	}

	/** Frames that took longer than `ms` (stalls). */
	stalls(ms = 50): number {
		return this.rows.filter((r) => r[1] > ms).length;
	}

	get size(): number {
		return this.rows.length;
	}

	csv(): string {
		const lines = ["time_ms,frame_ms,zoom,note", ...this.rows.map((r) => r.join(","))];
		return `${lines.join("\n")}\n`;
	}
}

/** The page's one frame log (the log drawer saves it). */
export const frameLog = new FrameLog();
