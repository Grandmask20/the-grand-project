import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { setAtlasGen } from "@/api/Http";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The app's state (refreshed by its events). */
export function useAppState() {
	const app = useAppClient();
	// tried for about 15 s before the page says the app isn't running (a busy moment isn't a stopped app)
	return useQuery({
		queryKey: AppQueryKeys.state,
		queryFn: async () => {
			const st = await app.getState();
			setAtlasGen(st.generation); // answers for the atlas open before are dropped from here on
			return st;
		},
		retry: 8,
		retryDelay: (n) => Math.min(4000, 500 * 2 ** n),
	});
}
