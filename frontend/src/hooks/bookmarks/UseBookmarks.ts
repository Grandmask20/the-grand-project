import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** Bookmarks by group. */
export function useBookmarks(enabled = true) {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.bookmarks, queryFn: () => app.getBookmarks(), enabled });
}
