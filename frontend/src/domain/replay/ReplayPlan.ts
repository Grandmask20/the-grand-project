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

/** The ground still hidden at each band of the replay (GeoJSON in lng / lat). */
export interface ReplayFog {
	bands: number;
	features: GeoJSON.Feature<GeoJSON.Polygon, { band: number }>[];
}
