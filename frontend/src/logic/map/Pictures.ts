/** The map's own pictures (MapSprites adds them); every other picture a layer asks for is an icon's. */
export const OWN_IMAGES = new Set(["node-square", "node-square-solid", "node-picture"]);

/** The tower picture over Tower landmarks (View: Pictures on the map). */
export const TOWER = "LostTower";

/** A white square for the "squares" map style, tinted by icon-color (an SDF image): hollow, or filled. */
export function squareImage(filled = false): { width: number; height: number; data: Uint8Array } {
	const n = 32;
	const data = new Uint8Array(n * n * 4);
	for (let y = 0; y < n; y++)
		for (let x = 0; x < n; x++) {
			const d = Math.min(x, y, n - 1 - x, n - 1 - y);
			const v = d >= 3 && (filled || d <= 7) ? 255 : 0; // the ring, or the whole square
			const i = (y * n + x) * 4;
			data[i] = 255;
			data[i + 1] = 255;
			data[i + 2] = 255;
			data[i + 3] = v;
		}
	return { width: n, height: n, data };
}
