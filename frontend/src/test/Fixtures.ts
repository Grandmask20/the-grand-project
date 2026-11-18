import type { AppState } from "@/domain/app/AppState";
import type { Meta } from "@/domain/app/Meta";
import type { AtlasCard } from "@/domain/atlas/AtlasCard";
import type { Bookmarks } from "@/domain/bookmarks/Bookmarks";
import type { TypeList } from "@/domain/find/TypeList";
import type { ItemInfo } from "@/domain/map/ItemInfo";

export const style = {
	path_style: "solid",
	path_width: 0,
	path_col: "",
	path_col1: "",
	map_col: "",
	map_size: 1,
	map_style: "circles",
	path_freq: 0,
	ov_towers: false,
	age_tint: "off",
	colour_spread: "plasma",
} as const;

export const state: AppState = {
	version: "1.17",
	atlas: {
		name: "default",
		path: "/atlases/default/atlas.json",
		maps: 80,
		icons: 9,
		shots: 4,
		landmarks: 4,
		bookmarks: 1,
	},
	model_version: 3,
	terrain_version: 2,
	filter_version: 1,
	busy: false,
	progress: null,
	status: "opened atlas.json",
	watch: { on: false, folder: "/atlases/default", picked: false },
	undo: [["shot_3.png"]],
	recent: ["shot_3.png", "shot_2.png"],
	waiting: [{ name: "lost.png", path: "/atlases/default/lost.png", tries: 2 }],
	seams: false,
	questions: [],
	log: ["12:00:00  opened"],
	debug: false,
	settings: {
		layers: { Terrain: true, Paths: true, Doubtful: false, Removed: false },
		multi_only: false,
		only_icon_maps: false,
		near_only: false,
		hidden_types: ["Ritual"],
		style: { ...style },
		replay: {},
		ui: {},
	},
	map: null,
};

export const meta: Meta = {
	version: "1.17",
	debug: false,
	colours: {
		node: { confirmed: "#28dcff", single: "#ff9600" },
		path_multi: "#28d7ff",
		path_single: "#ffb900",
		path_abyss: "#ff50e6",
		landmark: { City: "#50c8ff", Tower: "#64eb64", "Locked stronghold": "#965a96" },
		city: { Vaal: "#3296f0", Ezomyte: "#5ad25a" },
		bookmark: "#ffd228",
		select: "#ffffff",
		hit: "#ffff00",
		removed: "#ff4646",
		recent: "#ff00ff",
		background: "#141619",
		biome: { Forest: "#2f6b34" },
		land: "#2a2d30",
		status: {},
		no_icon: "#1b1e24",
		sessions: ["#ffc83c", "#3ca0ff"],
	},
	categories: ["Boss", "Other"],
	landmark_kinds: ["City", "Hall", "Tower"],
	city_types: ["Ezomyte", "Vaal", "Faridun"],
	biomes: ["Ezomyte city", "Vaal city", "Faridun city", "Breach stronghold"],
	potential_types: ["Potential city map", "Potential stronghold map"],
	place_icon: { City: "MapBossSpecial" },
	style_default: { ...style },
	colour_by: ["off", "by session", "oldest to newest", "times seen"],
	colour_spreads: ["plasma", "viridis"],
	tint_alpha: 0.32,
	replay: {
		types: ["by time", "spiral"],
		reveals: ["screenshots", "area"],
		cameras: ["whole atlas", "grow with atlas", "follow newest"],
		smoothing: { off: 0, light: 0.12 },
		speeds: [0.5, 1, 2],
		defaults: {
			type: "by time",
			reveal: "screenshots",
			camera: "whole atlas",
			smoothing: "light",
			length: 20,
			speed: 1,
			per_step: 1,
			video_width: 1280,
		},
		follow_span: 2.5,
		scan_column: 1920,
		spiral_pitch: 900,
	},
	recent_fade: 5,
	icon_units: 26,
	icon_min_px: 10,
};

export const types: TypeList = {
	sections: [
		{ title: "Places", rows: [{ label: "City", count: 2, icon: "MapBossSpecial", shown: true, aliases: "" }] },
		{
			title: "Map icons",
			rows: [
				{ label: "Breach", count: 3, icon: "Breach", shown: true, aliases: "breach unstable breaches" },
				{ label: "Ritual", count: 1, icon: "Ritual", shown: false, aliases: "ritual altars" },
			],
		},
	],
};

export const bookmarks: Bookmarks = {
	groups: [
		{
			name: "Boss",
			hidden: false,
			items: [{ id: 0, name: "big boss", note: "daily", x: 10, y: 20, created: "", hidden: false, shown: true }],
		},
		{ name: "Farm", hidden: true, items: [] },
	],
};

export const atlases: AtlasCard[] = [
	{
		name: "default",
		json: "/atlases/default/atlas.json",
		numbers: { maps: 80, icons: 9, shots: 4 },
		open: true,
		thumb: false,
	},
	{ name: "second", json: "/atlases/two/atlas.json", numbers: null, open: false, thumb: false },
];

export const nodeInfo: ItemInfo = {
	kind: "node",
	id: 12,
	title: "Map #12: Breach",
	lines: ["found in 2 of 2 screenshot(s) that show it", "position 440, 200"],
	x: 440,
	y: 200,
	node: 12,
	bookmark: null,
	suggest: { name: "Breach", group: "Breach" },
};
