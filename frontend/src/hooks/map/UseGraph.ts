import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { RouteGraph } from "@/logic/Routes";

/** The maps and paths shown, ready for routes. */
export function useRouteGraph(enabled = true): RouteGraph | null {
	const app = useAppClient();
	const q = useQuery({ queryKey: AppQueryKeys.graph, queryFn: () => app.getGraph(), enabled });
	return useMemo(() => (q.data ? new RouteGraph(q.data) : null), [q.data]);
}
