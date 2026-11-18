/** A Saved atlases card. */
export interface AtlasCard {
	name: string;
	json: string;
	numbers: { maps: number; icons: number; shots: number } | null;
	open: boolean;
	thumb: boolean;
}
