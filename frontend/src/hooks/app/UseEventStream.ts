import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { connectEvents, createEventHandler } from "@/api/EventStream";
import { useAppClient } from "@/hooks/app/UseAppClient";

/** Listens to the app's events while mounted. Returns whether the stream is connected. */
export function useEventStream(): boolean {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const [connected, setConnected] = useState(false);

	useEffect(() => {
		if (typeof EventSource === "undefined") return;
		const handle = createEventHandler(queryClient);
		const stop = connectEvents(
			app.eventsUrl(),
			(kind, data) => {
				setConnected(true);
				handle(kind, data);
			},
			() => {
				setConnected(true);
				void queryClient.invalidateQueries({ queryKey: AppQueryKeys.state }); // missed events while away
			},
		);
		return stop;
	}, [app, queryClient]);
	return connected;
}
