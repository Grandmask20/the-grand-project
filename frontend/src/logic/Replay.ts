import type { Meta } from "@/domain/app/Meta";
import type { Frames } from "@/domain/replay/Frames";
import type { ReplayPlan } from "@/domain/replay/ReplayPlan";

export type Box = [number, number, number, number];

/** Steps per second of playback: the timelapse lasts `length` seconds at 1x. */
export function stepsPerSecond(plan: ReplayPlan): number {
	const st = plan.settings;
	return (plan.n_steps / Math.max(1, st.length)) * st.speed;
}

/** Share of the way the camera moves in dt seconds (the same at any frame rate; 1 with smoothing off). */
export function ease(meta: Meta, smoothing: string, dt: number): number {
	const tau = meta.replay.smoothing[smoothing] ?? 0.12;
	return tau <= 0 ? 1 : 1 - Math.exp(-dt / tau);
}

/** The fog shown at a place: band `full` hidden, band `fading` fading in by `fade` (0 hidden .. 1 shown). */
export function fogBands(pos: number, nSteps: number, bands: number): { full: number; fading: number; fade: number } {
	const f = (Math.max(0, pos) / Math.max(1, nSteps)) * bands;
	const k = Math.floor(f);
	return { full: k + 1, fading: k, fade: f - k };
}

/** The step a click or drag on the timeline means. */
export function seekAt(clientX: number, left: number, width: number, nSteps: number): number {
	return Math.min(nSteps, Math.max(0, ((clientX - left) / Math.max(1, width)) * nSteps));
}

/** One step back or forward: whole steps, or a 40th of the sweep when revealing by area. */
export function stepFrom(pos: number, d: -1 | 1, plan: ReplayPlan): number {
	if (plan.area) return Math.min(plan.n_steps, Math.max(0, pos + (d * plan.n_steps) / 40));
	const next = d < 0 ? Math.ceil(pos - 1e-9) - 1 : Math.floor(pos + 1e-9) + 1;
	return Math.min(plan.n_steps, Math.max(0, next));
}

/** Screenshots and maps revealed by a place, and when the newest was taken. */
export function counts(plan: ReplayPlan, pos: number): { shots: number; maps: number; when: string; session: number } {
	const shots = plan.step_of.filter((s) => s < pos).length;
	const cur = Math.ceil(pos - 1e-9) - 1;
	const k = Math.min(plan.maps_at.length - 1, Math.floor(pos - 1e-9));
	const maps = k >= 0 ? (plan.maps_at[k] ?? 0) : 0;
	return {
		shots,
		maps,
		when: cur >= 0 && cur < plan.step_time.length ? plan.step_time[cur] : "",
		session: cur >= 0 ? (plan.step_session[cur] ?? 0) : (plan.step_session[0] ?? 0),
	};
}

function boxOf(frames: Frames, pick: (i: number) => boolean): Box | null {
	let x0 = Number.POSITIVE_INFINITY;
	let y0 = Number.POSITIVE_INFINITY;
	let x1 = Number.NEGATIVE_INFINITY;
	let y1 = Number.NEGATIVE_INFINITY;
	frames.frames.forEach((f, i) => {
		if (!pick(i)) return;
		for (const [x, y] of f.corners) {
			x0 = Math.min(x0, x);
			y0 = Math.min(y0, y);
			x1 = Math.max(x1, x);
			y1 = Math.max(y1, y);
		}
	});
	return Number.isFinite(x0) ? [x0, y0, x1, y1] : null;
}

/** Where the camera setting wants the view: a box to fit, or a centre and a width in atlas units. */
export function cameraTarget(meta: Meta, plan: ReplayPlan, frames: Frames, pos: number): Box | null {
	const s = plan.step_of;
	const p = Math.max(pos, 1e-9);
	const cam = plan.settings.camera;
	if (cam === "follow newest") {
		const newest = plan.area
			? (i: number) => s[i] < p && s[i] >= p - 0.05 * plan.n_steps
			: (i: number) => s[i] === Math.max(0, Math.ceil(p - 1e-9) - 1);
		const b =
			boxOf(frames, newest) ??
			(() => {
				const first = s.length ? Math.min(...s) : 0; // (once, and only when needed: CodeRabbit)
				return boxOf(frames, (i) => s[i] <= first);
			})();
		if (!b) return null;
		const cx = (b[0] + b[2]) / 2;
		const cy = (b[1] + b[3]) / 2;
		const half = (meta.replay.follow_span * 1920) / 2;
		return [cx - half, cy - half * 0.5625, cx + half, cy + half * 0.5625];
	}
	if (cam === "grow with atlas") {
		const b = growBox(meta, plan, frames, p);
		if (!b) return null;
		const pad = 0.08 * Math.max(b[2] - b[0], b[3] - b[1]);
		return [b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad];
	}
	return plan.bounds;
}

/** "Grow with atlas": the revealed screenshots by time; spiral / distance / scan lines, the sweep so far. */
function growBox(meta: Meta, plan: ReplayPlan, frames: Frames, pos: number): Box | null {
	const revealed = () => boxOf(frames, (i) => plan.step_of[i] < pos) ?? boxOf(frames, (i) => plan.step_of[i] <= 0);
	if (!plan.frame || !plan.step_key || !plan.n_steps) return revealed();
	const { start, right, top, span } = plan.frame;
	const k = Math.min(plan.n_steps - 1, Math.max(0, Math.ceil(pos - 1e-9) - 1));
	const key = plan.step_key[k];
	let box: Box;
	if (plan.kind === "scan lines") {
		const col = Math.floor(key / (span + 1));
		box = [right - (col + 1) * meta.replay.scan_column, top, right, top + span];
	} else {
		let r = key;
		if (plan.kind === "spiral") r = (Math.floor(key / meta.replay.spiral_pitch) + 1) * meta.replay.spiral_pitch;
		r = Math.max(r, 960);
		box = [start[0] - r, start[1] - r, start[0] + r, start[1] + r];
	}
	const a = plan.bounds;
	const b: Box = [Math.max(box[0], a[0]), Math.max(box[1], a[1]), Math.min(box[2], a[2]), Math.min(box[3], a[3])];
	return b[2] > b[0] && b[3] > b[1] ? b : revealed();
}

/**
 * The fog's cover of a spot revealed at `step` when the timelapse is at `pos` (0 shown .. 1 hidden). By time, a
 * screenshot shows from its step on (step < pos, as the counts). By area, a soft edge of `soft` steps ahead of pos:
 * centred on pos it left the last spots half-covered at the very end (CodeRabbit).
 */
export function fogCover(step: number, pos: number, area: boolean, soft: number): number {
	return area ? Math.min(1, Math.max(0, (step - pos) / soft)) : step < pos - 1e-9 ? 0 : 1;
}

/**
 * A fog cell's step from its stored value (0..65534 over 0..top). Steps by time are whole numbers: rounded, so step 1
 * isn't read as 0.99996 and shown a step early (CodeRabbit); by area they are fractions of the sweep.
 */
export function fogStep(v: number, top: number, area: boolean): number {
	const step = (v * top) / 65534;
	return area ? step : Math.round(step);
}

/** Whether a screenshot is revealed at a place (Colour by while replaying counts only those). */
export function revealed(plan: ReplayPlan | null, i: number, pos: number): boolean {
	return !plan || i >= plan.step_of.length || plan.step_of[i] < pos;
}
