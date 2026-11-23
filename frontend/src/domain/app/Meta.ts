import type { Style } from "@/domain/app/Style";

/** GET /api/meta: the app's colours and choices (one source with the Python side). */
export interface Meta {
	version: string;
	debug: boolean;
	colours: {
		node: Record<string, string>;
		/** A map node's bubble by its state (grey / blue / green / red); maps without one keep `node`'s. */
		node_state: Record<string, string>;
		path_multi: string;
		path_single: string;
		path_abyss: string;
		landmark: Record<string, string>;
		city: Record<string, string>;
		bookmark: string;
		select: string;
		hit: string;
		removed: string;
		recent: string;
		background: string;
		biome: Record<string, string>;
		land: string;
		status: Record<string, string>;
		no_icon: string;
		sessions: string[];
	};
	categories: string[];
	landmark_kinds: string[];
	city_types: string[];
	biomes: string[];
	potential_types: string[];
	place_icon: Record<string, string>;
	style_default: Style;
	colour_by: string[];
	colour_spreads: string[];
	tint_alpha: number;
	replay: {
		types: string[];
		reveals: string[];
		cameras: string[];
		smoothing: Record<string, number>;
		speeds: number[];
		defaults: ReplaySettings;
		follow_span: number;
		scan_column: number;
		spiral_pitch: number;
	};
	recent_fade: number;
	icon_units: number;
	icon_min_px: number;
	/** A bookmark pin's radius at size 1 (atlas units), how far above its spot a pin on the icon row sits, and where a
	 * pin can sit ("icon", "map node"). */
	bookmark_pin: number;
	icon_row_dy: number;
	bookmark_ats: string[];
}

export interface ReplaySettings {
	type: string;
	reveal: string;
	camera: string;
	smoothing: string;
	length: number;
	speed: number;
	per_step: number;
	video_width: number;
}
