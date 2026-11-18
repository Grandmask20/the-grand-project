import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The app's state (refreshed by its events). */
export function useAppState() {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.state, queryFn: () => app.getState() });
}
