import { useCallback } from "react";
import { usePlayer, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useRouteGraph } from "@/hooks/map/UseGraph";
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

	return { graph, player, setPlayer, routeTo, routeToNearest, clear };
}
