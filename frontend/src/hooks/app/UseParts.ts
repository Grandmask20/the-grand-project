import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/**
 * How far the map's parts are (map image, model). The app's events refresh it when a part changes; while
 * `watching` (the loading cover is up) it is also asked every PARTS_ASK_MS: a part's beat moves on without an
 * event, and only asking tells "still working" from "stopped" (the "are you still running?" check, user).
 */
export function useParts(watching: boolean) {
	const app = useAppClient();
	return useQuery({
		queryKey: AppQueryKeys.parts,
		queryFn: () => app.getParts(),
		refetchInterval: watching ? PARTS_ASK_MS : false,
	});
}

/** How often the loading cover asks how far the parts are (ms). */
export const PARTS_ASK_MS = 2000;

/** A part that hasn't moved on for this long (s) is named as such, with an offer to show the map anyway. It only says
 * so: nothing is shown or stopped by it (a big atlas keeps beating while it works, however long it takes). */
export const PART_QUIET_S = 30;
