import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { getAtlasGen, setAtlasGen } from "@/api/Http";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppStore } from "@/store/AppStore";

/** Queries that don't belong to one atlas: kept when another atlas opens. */
const ATLAS_FREE = new Set(["state", "meta", "atlases", "fs"]);

/** The app's state (refreshed by its events). */
export function useAppState() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	// tried for about 15 s before the page says the app isn't running (a busy moment isn't a stopped app)
	return useQuery({
		queryKey: AppQueryKeys.state,
		queryFn: async () => {
			const st = await app.getState();
			const before = getAtlasGen();
			setAtlasGen(st.generation); // answers for the atlas open before are dropped from here on
			if (before !== null && st.generation !== undefined && st.generation !== before) {
				// another atlas opened, made or closed (here or in another tab): what the page held for the one before
				// goes now, before anything draws with the new state (user: the old atlas's times-seen picture blinked
				// for a frame when the new map drew it from the old screenshot list while that was fetched again).
				// Emptied, not kept while refetching: selection, search, route, timelapse, waiting clicks too.
				useAppStore.getState().resetAtlas();
				void queryClient.resetQueries({ predicate: (q) => !ATLAS_FREE.has(String(q.queryKey[0])) });
			}
			return st;
		},
		retry: 8,
		retryDelay: (n) => Math.min(4000, 500 * 2 ** n),
	});
}
