import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The recent additions' outlines. */
export function useRecent(enabled = true) {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.recent, queryFn: () => app.getRecent(), enabled });
}
