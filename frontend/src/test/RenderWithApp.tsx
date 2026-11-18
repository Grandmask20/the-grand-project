import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { createAppClient } from "@/api/AppClient";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { AppClientProvider } from "@/providers/AppClientProvider";
import { useAppStore } from "@/store/AppStore";
import { fakeHttp } from "./FakeHttp";
import { meta, state } from "./Fixtures";

const initial = useAppStore.getState();

/** Puts the page store back as it starts (after each test). */
export function resetStore() {
	useAppStore.setState(initial, true);
}

/** Renders a part of the page with a fake app behind it (routes: "METHOD /api/path" -> answer). The state and the
 * meta are there from the start, as after the page loaded. */
export function renderWithApp(ui: ReactNode, routes: Record<string, unknown> = {}) {
	const { http, calls } = fakeHttp({ "GET /api/state": state, "GET /api/meta": meta, ...routes });
	const client = createAppClient(http);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false, staleTime: Number.POSITIVE_INFINITY }, mutations: { retry: false } },
	});
	// the state / meta a test gives (a value, not a function) are the starting ones too (CodeRabbit)
	const start = (key: string, fallback: unknown) =>
		key in routes && typeof routes[key] !== "function" ? routes[key] : fallback;
	queryClient.setQueryData(AppQueryKeys.state, structuredClone(start("GET /api/state", state)));
	queryClient.setQueryData(AppQueryKeys.meta, structuredClone(start("GET /api/meta", meta)));
	const user = userEvent.setup();
	const view = render(
		<QueryClientProvider client={queryClient}>
			<AppClientProvider client={client}>{ui}</AppClientProvider>
		</QueryClientProvider>,
	);
	return { user, calls, queryClient, ...view };
}
