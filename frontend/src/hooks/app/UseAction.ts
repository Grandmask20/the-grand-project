import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import type { AppClient } from "@/api/AppClient";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppStore } from "@/store/AppStore";

interface Options<R, V> {
	/** Queries to fetch again when it worked. */
	invalidate?: QueryKey[];
	onSuccess?: (result: R, vars: V) => void;
	/** Show a failure in the error box (default true). */
	report?: boolean;
}

/** A call that changes something in the app; failures go to the error box unless told otherwise. */
export function useAction<V = void, R = unknown>(fn: (app: AppClient, vars: V) => Promise<R>, opts: Options<R, V> = {}) {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const showError = useAppStore((s) => s.showError);
	return useMutation({
		mutationFn: (vars: V) => fn(app, vars),
		onSuccess: (result, vars) => {
			for (const key of opts.invalidate ?? []) void queryClient.invalidateQueries({ queryKey: key });
			opts.onSuccess?.(result, vars);
		},
		onError: (e) => {
			if (opts.report !== false) showError(e);
		},
	});
}
