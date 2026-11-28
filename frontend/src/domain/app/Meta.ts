import type { Style } from "@/domain/app/Style";
import type { DetectionSettings } from "@/domain/app/UiSettings";

/** GET /api/meta: the app's colours and choices (one source with the Python side). */
export interface Meta {
	version: string;
	debug: boolean;
	colours: {
		node: Record<string, string>;
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
	detection: DetectionChoices;
}

/** What the Experimental tab offers. */
export interface DetectionChoices {
	/** The detector this run of the app uses (the settings it started with). */
	active: DetectionSettings;
	/** The package RF-DETR needs that is not installed (the player release); null: it can run. */
	rf_detr_missing: string | null;
	/** The most workers this computer allows (one core is left for the window). */
	max_workers: number;
	devices: string[];
	default_model: string;
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
