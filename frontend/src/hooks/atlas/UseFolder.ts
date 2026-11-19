import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** A folder of this computer, for the file pickers ("" = home). */
export function useFolder(path: string | null, files: boolean) {
	const app = useAppClient();
	return useQuery({
		queryKey: AppQueryKeys.fs(path ?? "", files),
		queryFn: () => app.listDir(path ?? "", files),
		enabled: path !== null,
		retry: false,
		staleTime: 0,
	});
}
