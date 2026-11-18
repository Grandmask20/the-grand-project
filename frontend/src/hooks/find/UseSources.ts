import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { Point } from "@/logic/Geo";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The screenshots that show a spot, best view first. */
export function useSources(spot: Point | null) {
	const app = useAppClient();
	return useQuery({
		queryKey: AppQueryKeys.sources(spot?.[0] ?? 0, spot?.[1] ?? 0),
		queryFn: () => app.getSources(spot?.[0] ?? 0, spot?.[1] ?? 0),
		enabled: !!spot,
	});
}
