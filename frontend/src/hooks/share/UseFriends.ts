import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** Friends' atlases kept by this app (live sharing), and your own atlas to go back to. */
export function useFriends() {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.friends, queryFn: () => app.getFriends() });
}
