import { useMemo } from "react";
import type { UiSettings } from "@/domain/app/UiSettings";
import { useSettings } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";

/** The map layer a View setting shapes (changing it shows that layer while you work on it). */
export function layerOfStyle(key: string): string | null {
	if (key.startsWith("icon_") || key.startsWith("d3_icon_")) return "Icons";
	if (key.startsWith("path_") || key.startsWith("d3_path_") || key === "d3_solid_px") return "Paths";
	if (key.startsWith("map_")) return "Nodes";
	if (key.startsWith("d3_model_") || key === "d3_beams") return "3D models";
	return null;
}

/** The layers shown because of what you're doing, whatever their switches say (user: the debug marks, the icons
 * being restyled, a route, the biomes being drawn stayed hidden while you worked on them): the Debug page shows the
 * marks, a View setting its layer until you leave the tab, Route and a route shown the route, Biome select the
 * biomes. */
export function useRevealedLayers(): string[] {
	const tab = useAppStore((s) => s.tab);
	const page = useAppStore((s) => s.pages[s.tab]);
	const mode = useAppStore((s) => s.mode.kind);
	const routeShown = useAppStore((s) => s.route !== null || s.routeDraft !== null);
	const editing = useAppStore((s) => s.editing);
	return useMemo(() => {
		const out = new Set(editing);
		if (tab === "log" && page === "debug") out.add("Debug marks");
		if (mode === "route" || routeShown) out.add("Route");
		if (mode === "lasso") out.add("City & stronghold biomes");
		return [...out].sort();
	}, [tab, page, mode, routeShown, editing]);
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
