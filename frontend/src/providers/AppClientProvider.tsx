import { type ReactNode, useMemo } from "react";
import { type AppClient, createAppClient } from "@/api/AppClient";
import { AppClientContext } from "@/api/AppClientContext";
import { createHttp } from "@/api/Http";

/** Gives the page its client of the app (the same server that serves the page; tests pass their own). */
export function AppClientProvider({ client, children }: { client?: AppClient; children: ReactNode }) {
	const value = useMemo(() => client ?? createAppClient(createHttp()), [client]);
	return <AppClientContext.Provider value={value}>{children}</AppClientContext.Provider>;
}
