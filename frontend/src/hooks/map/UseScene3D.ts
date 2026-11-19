import { useQuery } from "@tanstack/react-query";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { vectorVersion } from "@/logic/map/Tiles";
import { useAppStore } from "@/store/AppStore";

/**
 * The 3D view's scene (icons, paths, models), fetched once per version while the map is tilted. The 3D layers were
 * fed from the vector tiles on screen before: rebuilt after every move, missing zoomed out, doubled at tile edges.
 */
export function useScene3D(enabled: boolean) {
	const app = useAppClient();
	const info = useAppState().data?.map;
	const v = info ? vectorVersion(info) : "";
	// the tab playing the timelapse gets each item's step (as its tiles)
	const replay = useAppStore((s) => s.replay?.plan.token);
	return useQuery({
		queryKey: ["scene3d", v, replay ?? 0],
		queryFn: () => app.getScene3d(v, replay),
		enabled: enabled && !!info,
		staleTime: Number.POSITIVE_INFINITY,
	});
}
