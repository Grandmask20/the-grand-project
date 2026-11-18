import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** Find: search the atlas (nothing for an empty search). */
export function useSearch(q: string) {
	const app = useAppClient();
	const text = q.trim();
	return useQuery({ queryKey: AppQueryKeys.search(text), queryFn: () => app.search(text), enabled: text.length > 0 });
}
