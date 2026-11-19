import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The app's colours and choices (never change while it runs). */
export function useMeta() {
	const app = useAppClient();
	return useQuery({
		queryKey: AppQueryKeys.meta,
		queryFn: () => app.getMeta(),
		retry: 8,
		retryDelay: (n) => Math.min(4000, 500 * 2 ** n),
	});
}
