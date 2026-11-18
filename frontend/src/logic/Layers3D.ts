/** Our 3D layers, bottom to top, all under the bookmarks. */
export const LAYERS_3D = ["models-3d-gl", "paths-3d-gl", "icons-3d-gl"];

/**
 * The layer a 3D layer goes in under: the next of LAYERS_3D above it that is on the map, else the bookmarks. Each
 * going in under the bookmarks stacked them in the order they were made, so toggling models off and on drew them
 * over the paths and icons (CodeRabbit).
 */
export function layerBelow(id: string, has: (id: string) => boolean): string {
	const above = LAYERS_3D.slice(LAYERS_3D.indexOf(id) + 1).find(has);
	return above ?? "bookmarks";
}
