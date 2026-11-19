import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./Http";

export function createQueryClient(): QueryClient {
	return new QueryClient({
		defaultOptions: {
			queries: {
				refetchOnWindowFocus: false,
				staleTime: Number.POSITIVE_INFINITY, // the app's events say when something changed
				retry: (failureCount: number, error: Error) =>
					failureCount < 2 && !(error instanceof ApiError && error.status >= 400 && error.status < 500),
			},
		},
	});
}
