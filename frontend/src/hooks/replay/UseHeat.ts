import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The "times seen" picture's box (the picture is fetched by the map); upto: only screenshots revealed so far. */
export function useHeat(enabled: boolean, upto?: number) {
	const app = useAppClient();
	return useQuery({
		queryKey: AppQueryKeys.heat(upto),
		queryFn: () => app.getHeat(upto),
		enabled,
		placeholderData: keepPreviousData,
	});
}
