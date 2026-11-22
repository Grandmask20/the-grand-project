import type { SkySpecification } from "maplibre-gl";

/**
 * The 3D view's sky and haze (MapLibre's "Sky, Fog, Terrain"; View: 3D view settings, Sky and fog): a dusky sky over
 * the horizon when the map is tilted far enough to show it, and the far ground and models fading into the horizon's
 * haze instead of black, so the view ends in a distance rather than a cut.
 */
export const SKY_COLOUR = "#1c1a2b";
export const HORIZON_COLOUR = "#4b3f5c";
export const FOG_COLOUR = "#2c2738";

export const SKY: SkySpecification = {
	"sky-color": SKY_COLOUR,
	"horizon-color": HORIZON_COLOUR,
	"fog-color": FOG_COLOUR,
	"sky-horizon-blend": 0.6,
	"horizon-fog-blend": 0.7,
	"fog-ground-blend": 0.5,
	"atmosphere-blend": 0,
};

/** A #rrggbb colour as rgb 0..1, for the shaders. */
export const rgb01 = (hex: string): [number, number, number] => {
	const n = Number.parseInt(hex.slice(1), 16);
	return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
};

/** The haze the ground and models fade into. */
export const FOG_RGB = rgb01(FOG_COLOUR);
