import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The Saved atlases cards. */
export function useAtlases() {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.atlases, queryFn: () => app.getAtlases() });
}
