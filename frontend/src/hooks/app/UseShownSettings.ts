import { useMemo } from "react";
import type { UiSettings } from "@/domain/app/UiSettings";
import { useSettings } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";

/** The layers shown because of what you're doing, whatever their switches say (user: the debug marks, the icons
 * being restyled, a route, the biomes being drawn stayed hidden while you worked on them): the Debug page shows the
 * marks, a View setting in use its layer (RevealWhileUsed), Route while its maps are picked the route, Biome select
 * the biomes. A route found or tracked follows the Routes switch (user: Routes off still showed it). */
export function useRevealedLayers(): string[] {
	const tab = useAppStore((s) => s.tab);
	const page = useAppStore((s) => s.pages[s.tab]);
	const mode = useAppStore((s) => s.mode.kind);
	const picking = useAppStore((s) => s.routeDraft !== null);
	const editing = useAppStore((s) => s.editing);
	return useMemo(() => {
		const out = new Set(editing.filter((k) => !k.startsWith(VIEW_NOTICE))); // (notices aren't layers)
		if (tab === "log" && page === "debug") out.add("Debug marks");
		if (mode === "route" || picking) out.add("Route");
		if (mode === "lasso") out.add("City & stronghold biomes");
		return [...out].sort();
	}, [tab, page, mode, picking, editing]);
}

/** A View setting of the other view in use (3D view settings while the map is flat, or the other way round): held as
 * "view:3d" / "view:2d", a notice over the map says it doesn't show (user: 3D settings revealed the flat paths). */
export const VIEW_NOTICE = "view:";

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
