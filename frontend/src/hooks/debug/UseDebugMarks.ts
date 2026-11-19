import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The debug marks of the open atlas (internal copy only). */
export function useDebugMarks(enabled: boolean) {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.debug, queryFn: () => app.getDebug(), enabled });
}
