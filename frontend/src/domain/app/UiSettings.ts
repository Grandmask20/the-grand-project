import type { Style } from "@/domain/app/Style";

/** The page's settings kept by the app (they change what the map's tiles hold). */
export interface UiSettings {
	layers: Record<string, boolean>;
	multi_only: boolean;
	only_icon_maps: boolean;
	near_only: boolean;
	hidden_types: string[];
	style: Style;
	replay: Record<string, unknown>;
	ui: PageSettings;
}

/** Settings only the page uses, kept with the others. */
export interface PageSettings {
	background?: Background;
	player?: { x: number; y: number; node: number } | null;
	labels?: boolean;
	side_width?: number;
	/** Which side of the window the side panel is on (user). */
	side?: "left" | "right";
	/** The Layers dock unfolded (folded by default). */
	layers_open?: boolean;
}

export type Background = "picture" | "vector" | "none";

export type SettingsChange = Partial<Omit<UiSettings, "style" | "ui">> & {
	style?: Partial<Style> & { reset?: boolean };
	ui?: Partial<PageSettings>;
};
