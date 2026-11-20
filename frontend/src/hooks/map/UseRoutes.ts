import { useCallback, useRef } from "react";
import type { SavedRoute } from "@/domain/bookmarks/Bookmarks";
import { usePlayer, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import type { RouteGraph } from "@/logic/Routes";
import { legsOf, routeLines, savedRouteOf, visitOrder } from "@/logic/SavedRoutes";
import { useAppStore } from "@/store/AppStore";
import { plural } from "@/utils/Format";

/** Directions: your position (a map) and routes from it, fewest maps first. */
export function useRoutes() {
	const graph = useRouteGraph();
	const { player, atlas } = usePlayer();
	const update = useUpdateSettings();
	const setRoute = useAppStore((s) => s.setRoute);
	const setMode = useAppStore((s) => s.setMode);

	const setPlayer = useCallback(
		(node: number) => {
			const p = graph?.at(node);
			if (p) update.mutate({ ui: { player: { x: p[0], y: p[1], node, atlas } } });
		},
		[graph, update, atlas],
	);

	const need = useCallback(() => {
		if (player && graph?.has(player.node)) return player.node;
		setRoute({ path: [], message: "Set your position first: click the map you are on." });
		setMode({ kind: "player" });
		return null;
	}, [player, graph, setRoute, setMode]);

	// a route found is tracked as every route is (user: Route here showed a list, Track now maps left and Next map)
	const show = useCallback(
		(path: number[] | null, none: string) => (path ? trackRef.current(path) : setRoute({ path: [], message: none })),
		[setRoute],
	);

	const routeTo = useCallback(
		(node: number) => {
			const from = need();
			if (from === null || !graph) return;
			show(
				from === node ? [node] : graph.shortest(from, (u) => u === node),
				`No path from your map to map #${node} in this atlas.`,
			);
		},
		[need, graph, show],
	);

	const routeToNearest = useCallback(
		(icon: string, label = icon) => {
			const from = need();
			if (from === null || !graph) return;
			show(
				graph.shortest(from, (u) => graph.iconsOf(u).includes(icon)),
				`No reachable map with ${label}.`,
			);
		},
		[need, graph, show],
	);

	const clear = useCallback(() => setRoute(null), [setRoute]);

	/** Forget your position (user: an "I'm here" clicked by mistake couldn't be taken back). */
	const clearPlayer = useCallback(() => {
		update.mutate({ ui: { player: null } });
		setRoute(null);
	}, [update, setRoute]);

	const flyTo = useAppStore((s) => s.flyTo);
	const setTab = useAppStore((s) => s.setTab);

	/** Track a route (Route in the top bar: Track now; Route here; a saved route: Start tracking now): it starts on its
	 * first map, the Route page shows how many maps are left, and Next map moves on one (user). The route marks where
	 * you are on it; your position (I'm here) stays as it is. `saved`: the saved route's bookmark, when it is one. */
	const trackRoute = useCallback(
		(path: number[], saved?: number) => {
			if (path.length < 1) return;
			setRoute({ path, message: tracking(path, 0), at: 0, ...(saved !== undefined ? { saved } : {}) });
			const p = graph?.at(path[0]);
			if (p) flyTo(p[0], p[1], 0.6);
			setTab("route");
		},
		[setRoute, graph, flyTo, setTab],
	);
	const trackRef = useRef(trackRoute);
	trackRef.current = trackRoute;

	/** Track a saved route (Start tracking now on it in Bookmarks): its maps as they are on this atlas, branches run
	 * where they split off. False when its maps aren't on this atlas any more. */
	const trackSaved = useCallback(
		(r: SavedRoute, id: number) => {
			const legs = graph ? legsOf(r, graph) : null;
			if (!legs) return false;
			trackRoute(visitOrder(legs), id);
			return true;
		},
		[graph, trackRoute],
	);

	/** The next map of the route tracked, and the map goes there (the maps passed again on the way back from a branch
	 * are skipped: they're run already). */
	const nextMap = useCallback(() => {
		const r = useAppStore.getState().route;
		if (!r || r.at === undefined) return;
		const at = nextNew(r.path, r.at);
		if (at === null) return;
		setRoute({ ...r, at, message: tracking(r.path, at) });
		const p = graph?.at(r.path[at]);
		if (p) flyTo(p[0], p[1], 0.6);
	}, [setRoute, graph, flyTo]);

	return { graph, player, setPlayer, clearPlayer, routeTo, routeToNearest, clear, trackRoute, trackSaved, nextMap };
}

/** The place in a route tracked of the next map not run yet, or null at its end. */
export function nextNew(path: number[], at: number): number | null {
	const run = new Set(path.slice(0, at + 1));
	for (let i = at + 1; i < path.length; i++) if (!run.has(path[i])) return i;
	return null;
}

/** How many maps of a tracked route are left: each once, none run already (a branch's way back is not counted). */
export function mapsLeft(path: number[], at: number): number {
	const run = new Set(path.slice(0, at + 1));
	return new Set(path.slice(at + 1).filter((m) => !run.has(m))).size;
}

/** What the Route page says while a route is tracked: how many maps are left (each once). */
export function tracking(path: number[], at: number): string {
	const left = mapsLeft(path, at);
	return left > 0 ? `${plural(left, "map")} left` : "You're there: the route's last map.";
}

/** A route to save as a bookmark (Save route): its ends' numbers, how many maps it runs, its maps and its line. */
export function savedRoute(graph: RouteGraph, path: number[]): SavedRoute {
	return savedRouteOf([path], graph);
}

/** A route bookmark's name in the list: "route1 (map #252 -> map #262)" (user). */
export function routeTitle(name: string, r: SavedRoute): string {
	return `${name} (map #${r.from} -> map #${r.to})`;
}

/** The area a saved route covers, with room round it so it doesn't touch the view's edges (user's example: about a
 * tenth of its size each side), as [x0, y0, x1, y1] in atlas units. */
export function routeBox(r: SavedRoute): [number, number, number, number] {
	const pts = routeLines(r).flat();
	if (!pts.length) return [0, 0, 0, 0];
	const xs = pts.map((p) => p[0]);
	const ys = pts.map((p) => p[1]);
	const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
	const pad = Math.max(x1 - x0, y1 - y0, 200) * ROUTE_PAD;
	return [x0 - pad, y0 - pad, x1 + pad, y1 + pad];
}

const ROUTE_PAD = 0.12; // a saved route fitted in the view: room round it, a share of its longest side
