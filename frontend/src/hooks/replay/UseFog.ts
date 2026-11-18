import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** The replay's fog bands (the plan's, worked out by the app). */
export function useFog(planKey: string | null) {
	const app = useAppClient();
	return useQuery({ queryKey: [...AppQueryKeys.fog, planKey], queryFn: () => app.getFog(), enabled: !!planKey });
}
