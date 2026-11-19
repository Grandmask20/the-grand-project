import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** Every map / place of one type (null: none asked for). */
export function useListType(type: string | null) {
	const app = useAppClient();
	return useQuery({
		queryKey: AppQueryKeys.list(type ?? ""),
		queryFn: async () => (await app.listType(type ?? "")).results,
		enabled: !!type,
	});
}
