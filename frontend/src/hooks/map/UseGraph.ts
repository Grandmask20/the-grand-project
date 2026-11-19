import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { Graph } from "@/domain/map/Graph";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { RouteGraph } from "@/logic/Routes";

/** One RouteGraph per graph answer (made once, whoever asks first). */
const built = new WeakMap<Graph, RouteGraph>();
function routeGraphOf(g: Graph): RouteGraph {
	let r = built.get(g);
	if (!r) {
		r = new RouteGraph(g);
		built.set(g, r);
	}
	return r;
}

/** The maps and paths shown, ready for routes. */
export function useRouteGraph(enabled = true): RouteGraph | null {
	const app = useAppClient();
	const q = useQuery({ queryKey: AppQueryKeys.graph, queryFn: () => app.getGraph(), enabled });
	return useMemo(() => (q.data ? routeGraphOf(q.data) : null), [q.data]);
}

/** The maps and paths, waited for when they aren't in yet: a click that needs them (I'm here, Route, Adjust route)
 * waits instead of being dropped (CodeRabbit-style review: they load when the mode starts, and a quick click came
 * first; your log: I'm here ended with no position). */
export function useLoadRouteGraph(): () => Promise<RouteGraph> {
	const app = useAppClient();
	const queryClient = useQueryClient();
	return useCallback(
		async () =>
			routeGraphOf(await queryClient.ensureQueryData({ queryKey: AppQueryKeys.graph, queryFn: () => app.getGraph() })),
		[app, queryClient],
	);
}
