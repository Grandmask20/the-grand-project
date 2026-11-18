/** The View tab's styles (STYLE_DEFAULT plus colours by key: city_col_<type>, lm_col_<kind>). */
export interface Style {
	path_style: "solid" | "dashed" | "dotted";
	path_width: number;
	path_col: string;
	path_col1: string;
	map_col: string;
	map_size: number;
	map_style: "circles" | "squares" | "map icons" | "hidden";
	/** Circles and squares filled with the map's colour, or a border around the icon's colour (user). */
	map_fill: "solid" | "bordered";
	/** The border's colour when bordered ("" = by status). */
	map_border: string;
	path_freq: number;
	ov_towers: boolean;
	age_tint: string;
	colour_spread: string;
	[key: string]: string | number | boolean;
}
