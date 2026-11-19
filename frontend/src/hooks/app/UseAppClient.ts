import { useContext } from "react";
import type { AppClient } from "@/api/AppClient";
import { AppClientContext } from "@/api/AppClientContext";

export function useAppClient(): AppClient {
	const client = useContext(AppClientContext);
	if (!client) throw new Error("useAppClient must be used inside AppClientProvider");
	return client;
}
