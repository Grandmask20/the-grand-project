import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { sameAtlas } from "@/api/Http";
import type { Bookmarks, SavedRoute } from "@/domain/bookmarks/Bookmarks";
import type { ItemInfo } from "@/domain/map/ItemInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useBookmarks } from "@/hooks/bookmarks/UseBookmarks";
import { useLoadRouteGraph } from "@/hooks/map/UseGraph";
import { tracking } from "@/hooks/map/UseRoutes";
import type { Point } from "@/logic/Geo";
import type { RouteGraph } from "@/logic/Routes";
import { addMap, legsOf, nearestOn, removeMap, savedRouteOf, visitOrder } from "@/logic/SavedRoutes";
import { type MapMode, useAppStore } from "@/store/AppStore";

/** A saved route's edits: run one after another in click order (picking, working out, saving: CodeRabbit, an add that
 * waited longer than a later remove landed after it), and the route as the last edit left it, kept until the list
 * shows it (ending Adjust route with saves still going lost it, and the next edit built on an older route). For the
 * atlas it was made in only (`still`). */
interface RouteEdits {
	chain: Promise<unknown>;
	route: SavedRoute | null;
	pending: number;
	still: () => boolean;
}
const edits = new Map<number, RouteEdits>();

const listedRoute = (data: Bookmarks | undefined, id: number) =>
	data?.groups.flatMap((g) => g.items).find((b) => b.id === id)?.route;

/** Adjust route (a saved route's right-click menu in Bookmarks): a map clicked goes on the route (past an end, before
 * its start, or a branch off its side), a map right-clicked comes off it (removeMap) (user). `pick` says what is at a
 * spot; `reach` is how near (atlas units) a right-click takes the route's own map. */
export function useAdjustRoute(pick: (at: Point) => Promise<ItemInfo | null>) {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const loadGraph = useLoadRouteGraph();
	const showError = useAppStore((s) => s.showError);
	const setMode = useAppStore((s) => s.setMode);

	// what the list shows now is the route: the kept one goes, once no edit of it is still going
	const listed = useBookmarks().data;
	useEffect(() => {
		for (const [id, q] of edits) {
			const same = q.route && JSON.stringify(listedRoute(listed, id)) === JSON.stringify(q.route);
			if (!q.still() || (q.pending === 0 && (same || !q.route))) edits.delete(id);
		}
	}, [listed]);

	return useCallback(
		(at: Point, add: boolean, started: MapMode, reach: number) => {
			if (started.kind !== "route-edit") return Promise.resolve();
			const id = started.id;
			let q = edits.get(id);
			if (!q?.still()) {
				q = { chain: Promise.resolve(), route: null, pending: 0, still: sameAtlas() };
				edits.set(id, q);
			}
			const mine = q;
			mine.pending++;
			const job = mine.chain.then(async () => {
				const current = () => mine.still() && useAppStore.getState().mode === started;
				if (!current()) return; // (left meanwhile: Esc, End, another atlas)
				const [hit, graph] = await Promise.all([pick(at), loadGraph()]);
				if (!current()) return;
				const before = mine.route ?? listedRoute(queryClient.getQueryData<Bookmarks>(AppQueryKeys.bookmarks), id);
				if (!before) return setMode({ kind: "normal" }); // (deleted meanwhile)
				const next = change(before, hit, at, add, graph, reach);
				if (typeof next === "string") return showError(next, true);
				const route = savedRouteOf(next, graph);
				mine.route = route;
				// the route tracked is this one: it follows, on the map you are on
				const tracked = useAppStore.getState().route;
				if (tracked?.saved === id && tracked.at !== undefined) {
					const path = visitOrder(next);
					const at = Math.max(0, path.indexOf(tracked.path[tracked.at]));
					useAppStore.getState().setRoute({ path, at, saved: id, message: tracking(path, at) });
				}
				// sent only to the atlas it was made in (the request reads the atlas open when sent: CodeRabbit)
				if (!mine.still()) return;
				try {
					await app.setBookmarkRoute(id, route);
				} catch (err) {
					mine.route = null; // (the list holds what was saved)
					throw err;
				}
			});
			mine.chain = job.catch(() => {}); // (a failed edit doesn't stop the next)
			return job.finally(() => {
				mine.pending--;
			});
		},
		[app, queryClient, loadGraph, pick, showError, setMode],
	);
}

/** The route with the map clicked added or taken off, or why not. */
function change(
	before: SavedRoute,
	hit: ItemInfo | null,
	at: Point,
	add: boolean,
	graph: RouteGraph,
	reach: number,
): ReturnType<typeof addMap> {
	const legs = legsOf(before, graph);
	if (!legs) return "This route's maps aren't on this atlas any more.";
	const picked = hit?.kind === "node" ? hit.id : (hit?.node ?? graph.nearest(at[0], at[1]));
	// taking maps off: the route's own map nearest the click, near enough (an icon beside it can belong to another map)
	const node = add ? picked : (nearestOn(legs, graph, at, reach) ?? picked);
	if (node === null) return "No map there.";
	return add ? addMap(legs, node, graph) : removeMap(legs, node, graph);
}
