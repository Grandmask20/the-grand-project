import { useMemo } from "react";
import type { UiSettings } from "@/domain/app/UiSettings";
import { useSettings } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";

/** The layers shown because of what you're doing, whatever their switches say (user: the debug marks, the icons
 * being restyled, a route, the biomes being drawn stayed hidden while you worked on them): the Debug page shows the
 * marks, a View setting in use its layer (RevealWhileUsed), Route while its maps are picked the route, Biome select
 * the biomes. A route found or tracked follows the Routes switch (user: Routes off still showed it). */
export function useRevealedLayers(): string[] {
	const debugOpen = useAppStore((s) => s.logOpen && s.logPage === "debug");
	const mode = useAppStore((s) => s.mode.kind);
	const picking = useAppStore((s) => s.routeDraft !== null);
	const editing = useAppStore((s) => s.editing);
	return useMemo(() => {
		const out = new Set(editing);
		if (debugOpen) out.add("Debug marks");
		if (mode === "route" || picking) out.add("Route");
		if (mode === "lasso") out.add("City & stronghold biomes");
		return [...out].sort();
	}, [debugOpen, mode, picking, editing]);
}

/** The settings as the map draws them: the saved ones, with the layers you're working on switched on (the saved
 * switches stay as they are). */
export function useShownSettings(): UiSettings | undefined {
	const settings = useSettings();
	const revealed = useRevealedLayers();
	return useMemo(() => {
		if (!settings || !revealed.length) return settings;
		const layers = { ...settings.layers };
		for (const k of revealed) layers[k] = true;
		return { ...settings, layers };
	}, [settings, revealed]);
}
