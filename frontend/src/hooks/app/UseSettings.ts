import { useMutation, useQueryClient } from "@tanstack/react-query";
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
		mutationFn: (change: SettingsChange) => app.updateSettings(change),
		onMutate: (change) => {
			queryClient.setQueryData<AppState>(AppQueryKeys.state, (s) =>
				s ? { ...s, settings: merge(s.settings, change) } : s,
			);
		},
		onSuccess: (settings, change) => {
			queryClient.setQueryData<AppState>(AppQueryKeys.state, (s) => (s ? { ...s, settings } : s));
			void queryClient.invalidateQueries({ queryKey: AppQueryKeys.types });
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
