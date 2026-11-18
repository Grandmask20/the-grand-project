import { useQuery } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { ItemRef } from "@/domain/map/ItemKind";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** An item's details, kept fresh when the model changes. */
export function useInfo(item: ItemRef | null) {
	const app = useAppClient();
	return useQuery({
		queryKey: AppQueryKeys.info(item?.kind ?? "node", item?.id ?? -1),
		queryFn: () => app.getInfo(item?.kind ?? "node", item?.id ?? -1),
		enabled: !!item,
		retry: false,
	});
}
