import type { ReplaySettings } from "@/domain/app/Meta";

/** The timelapse worked out by the app (POST /api/replay/open). */
export interface ReplayPlan {
	settings: ReplaySettings;
	n_steps: number;
	kind: string;
	area: boolean;
	step_of: number[];
	ticks: number[];
	step_time: string[];
	step_session: number[];
	real: string;
	real_seconds: number;
	frame: { start: [number, number]; right: number; top: number; span: number } | null;
	step_key: number[] | null;
	maps_at: number[];
	bounds: [number, number, number, number];
}

/** GET /api/replay/fog: the step each spot's ground is revealed at, on a grid over the atlas. */
export interface ReplayFog {
	field: {
		w: number;
		h: number;
		/** The step a cell value of 65534 means (values scale linearly; 65535 = no ground there). */
		top: number;
		/** Base64 little-endian uint16 per cell, row by row. */
		data: string;
		/** [lng, lat] of the grid's top left, top right, bottom right, bottom left. */
		corners: [[number, number], [number, number], [number, number], [number, number]];
	} | null;
}
