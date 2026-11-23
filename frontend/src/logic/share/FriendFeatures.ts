import type { SharedAtlas, SharedPlayer } from "@/domain/share/SharedAtlas";
import { Geo } from "@/logic/Geo";
import { collection, EMPTY, line, point } from "@/logic/map/Features";

/** The icon pictures' size on the friend's map (the 64 px sprite at 0.4: 26 px). */
export const ICON_SCALE = 0.4;
/** Screen px between a map's icons drawn in a row above it, and the row's height above the map. */
export const ICON_GAP = 28;
export const ICON_UP = 24;

/** A friend's atlas as GeoJSON for its own map (FriendAtlas): paths, maps, their icons, landmarks, them. */
export function friendFeatures(atlas: SharedAtlas, player: SharedPlayer | null) {
	const geo = new Geo(atlas.info);
	const at = new Map(atlas.nodes.map((n) => [n.id, geo.toLngLat(n.x, n.y)] as const));
	const paths = collection(
		atlas.edges.flatMap((e) => {
			if (e.line) return [line(e.line.map(([x, y]) => geo.toLngLat(x, y)))];
			const [a, b] = [at.get(e.a), at.get(e.b)];
			return a && b ? [line([a, b])] : [];
		}),
	);
	const maps = collection(atlas.nodes.map((n) => point(geo.toLngLat(n.x, n.y), { id: n.id, status: n.status })));
	// a map's icons in a row above it, each once (as the atlas's own map shows them)
	const icons = collection(
		atlas.nodes.flatMap((n) => {
			const names = [...new Set(n.icons)];
			return names.map((name, k) =>
				// (icon-offset counts in the picture's own px: divided by its scale)
				point(geo.toLngLat(n.x, n.y), {
					name,
					off: [((k - (names.length - 1) / 2) * ICON_GAP) / ICON_SCALE, -ICON_UP / ICON_SCALE],
				}),
			);
		}),
	);
	const landmarks = collection(
		atlas.landmarks.map((l) => point(geo.toLngLat(l.x, l.y), { label: l.label, kind: l.kind })),
	);
	const here = player ? collection([point(geo.toLngLat(player.x, player.y))]) : EMPTY;
	return { paths, maps, icons, landmarks, here, iconNames: [...new Set(atlas.nodes.flatMap((n) => n.icons))] };
}
