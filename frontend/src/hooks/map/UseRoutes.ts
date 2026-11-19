import { useCallback } from "react";
import type { SavedRoute } from "@/domain/bookmarks/Bookmarks";
import { usePlayer, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useRouteGraph } from "@/hooks/map/UseGraph";
import type { RouteGraph } from "@/logic/Routes";
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

	const show = useCallback(
		(path: number[] | null, none: string) =>
			setRoute(path ? { path, message: `${plural(path.length - 1, "map")} to run` } : { path: [], message: none }),
		[setRoute],
	);

	const routeTo = useCallback(
		(node: number) => {
			const from = need();
			if (from === null || !graph) return;
			if (from === node) return setRoute({ path: [node], message: "You are already there." });
			show(
				graph.shortest(from, (u) => u === node),
				`No path from your map to map #${node} in this atlas.`,
			);
		},
		[need, graph, setRoute, show],
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

	/** Track a route (Route in the top bar, Track now): you are on its first map, the Route page shows how many maps
	 * are left, and Next map moves you on one (user). */
	const trackRoute = useCallback(
		(path: number[]) => {
			if (path.length < 1) return;
			setRoute({ path, message: tracking(path, 0), at: 0 });
			setPlayer(path[0]);
			const p = graph?.at(path[0]);
			if (p) flyTo(p[0], p[1], 0.6);
			setTab("route");
		},
		[setRoute, setPlayer, graph, flyTo, setTab],
	);

	/** The next map of the route tracked: it is where you are now, and the map goes there. */
	const nextMap = useCallback(() => {
		const r = useAppStore.getState().route;
		if (!r || r.at === undefined || r.at + 1 >= r.path.length) return;
		const at = r.at + 1;
		setRoute({ ...r, at, message: tracking(r.path, at) });
		setPlayer(r.path[at]);
		const p = graph?.at(r.path[at]);
		if (p) flyTo(p[0], p[1], 0.6);
	}, [setRoute, setPlayer, graph, flyTo]);

	return { graph, player, setPlayer, clearPlayer, routeTo, routeToNearest, clear, trackRoute, nextMap };
}

/** What the Route page says while a route is tracked: how many maps are left. */
export function tracking(path: number[], at: number): string {
	const left = path.length - 1 - at;
	return left > 0 ? `${plural(left, "map")} left` : "You're there: the route's last map.";
}

/** A route to save as a bookmark (Save route): its ends' numbers, how many maps it runs, and its line. */
export function savedRoute(graph: RouteGraph, path: number[]): SavedRoute {
	return {
		from: path[0],
		to: path[path.length - 1],
		maps: path.length - 1,
		line: graph.line(path).map(([x, y]) => [x, y] as [number, number]),
	};
}

/** A route bookmark's name in the list: "route1 (map #252 -> map #262)" (user). */
export function routeTitle(name: string, r: SavedRoute): string {
	return `${name} (map #${r.from} -> map #${r.to})`;
}

/** The area a saved route covers, with room round it so it doesn't touch the view's edges (user's example: about a
 * tenth of its size each side), as [x0, y0, x1, y1] in atlas units. */
export function routeBox(r: SavedRoute): [number, number, number, number] {
	const xs = r.line.map((p) => p[0]);
	const ys = r.line.map((p) => p[1]);
	const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
	const pad = Math.max(x1 - x0, y1 - y0, 200) * ROUTE_PAD;
	return [x0 - pad, y0 - pad, x1 + pad, y1 + pad];
}

const ROUTE_PAD = 0.12; // a saved route fitted in the view: room round it, a share of its longest side
