import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** Find's type list. */
export function useTypes(enabled = true) {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.types, queryFn: () => app.getTypes(), enabled });
}
