import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** Every screenshot's outline, session and age (Colour by, the replay's camera). */
export function useFrames(enabled: boolean) {
	const app = useAppClient();
	return useQuery({ queryKey: AppQueryKeys.frames, queryFn: () => app.getFrames(), enabled });
}
