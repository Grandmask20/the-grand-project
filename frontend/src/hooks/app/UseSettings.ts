import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { AppState } from "@/domain/app/AppState";
import type { Style } from "@/domain/app/Style";
import type { SettingsChange, UiSettings } from "@/domain/app/UiSettings";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";

/** The page's settings kept by the app. */
export function useSettings(): UiSettings | undefined {
	return useAppState().data?.settings;
}

/** Your position for routes, when it was set in the open atlas (another atlas's map ids mean other maps: user). */
export function usePlayer() {
	const state = useAppState().data;
	const player = state?.settings.ui.player ?? null;
	const atlas = state?.atlas?.path ?? "";
	return { player: player && atlas && player.atlas === atlas ? player : null, atlas };
}

/** Change settings: shown at once, then saved by the app (the map's tiles follow its new filter version). */
export function useUpdateSettings() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const showError = useAppStore((s) => s.showError);
	return useMutation({
		mutationKey: SETTINGS_KEY,
		mutationFn: (change: SettingsChange) => app.updateSettings(change),
		// one at a time, in order: a slider drag or quick checkbox clicks sent several, and an earlier answer
		// arriving last put the old value back (CodeRabbit)
		scope: { id: "settings" },
		onMutate: async (change) => {
			// a state fetch already on its way holds the old settings: dropped, not applied after this (CodeRabbit)
			await queryClient.cancelQueries({ queryKey: AppQueryKeys.state });
			queryClient.setQueryData<AppState>(AppQueryKeys.state, (s) =>
				s ? { ...s, settings: merge(s.settings, change) } : s,
			);
		},
		onSuccess: (settings, change) => {
			// the app's answer, with the changes still waiting their turn on top: written alone, it put back what
			// those had already changed on the page until their own answers came (user: icon ticks "lagged behind
			// by 1 step", a tick showed the one before)
			const waiting = waitingChanges(queryClient, change);
			queryClient.setQueryData<AppState>(AppQueryKeys.state, (s) =>
				s ? { ...s, settings: waiting.reduce(merge, settings) } : s,
			);
			// Find's type list only follows these (it was fetched again after every change: 486 times in one
			// session, a slider drag sending one per step)
			if ("near_only" in change || "hidden_types" in change || change.layers)
				void queryClient.invalidateQueries({ queryKey: AppQueryKeys.types });
			// routes go along the paths shown
			if (change.style && "path_freq" in change.style)
				void queryClient.invalidateQueries({ queryKey: AppQueryKeys.graph });
			// Colour by's colours come with the screenshots' outlines and the heat picture (user: switching them
			// changed nothing on the map)
			if (change.style && ("colour_spread" in change.style || "age_tint" in change.style || change.style.reset)) {
				void queryClient.invalidateQueries({ queryKey: AppQueryKeys.frames });
				void queryClient.invalidateQueries({ queryKey: ["heat"] });
			}
		},
		onError: (e) => {
			showError(e);
			void queryClient.invalidateQueries({ queryKey: AppQueryKeys.state });
		},
	});
}

const SETTINGS_KEY = ["settings"];

/** The settings changes sent after `done` and not answered yet, oldest first.
 *
 * @param queryClient The page's query client.
 * @param done The change whose answer just came (its own mutation is still pending while its onSuccess runs).
 * @returns Their changes, in the order they were made.
 */
export function waitingChanges(queryClient: QueryClient, done: SettingsChange): SettingsChange[] {
	return queryClient
		.getMutationCache()
		.findAll({ mutationKey: SETTINGS_KEY, status: "pending" })
		.filter((m) => m.state.variables !== done && m.state.variables !== undefined)
		.sort((a, b) => a.mutationId - b.mutationId)
		.map((m) => m.state.variables as SettingsChange);
}

/** Show a change on the page without saving it (a slider while it is dragged; saved when let go).
 *
 * @returns A function taking the change.
 */
export function usePreviewSettings() {
	const queryClient = useQueryClient();
	return (change: SettingsChange) =>
		queryClient.setQueryData<AppState>(AppQueryKeys.state, (s) =>
			s ? { ...s, settings: merge(s.settings, change) } : s,
		);
}

/** Settings with a change applied (as the app does). */
export function merge(s: UiSettings, c: SettingsChange): UiSettings {
	const { style, ui, layers, ...rest } = c;
	const { reset, ...changed } = style ?? {};
	const nextStyle = (reset ? { ...s.style } : { ...s.style, ...changed }) as Style;
	return {
		...s,
		...rest,
		layers: { ...s.layers, ...(layers ?? {}) },
		style: nextStyle,
		ui: { ...s.ui, ...(ui ?? {}) },
	};
}
