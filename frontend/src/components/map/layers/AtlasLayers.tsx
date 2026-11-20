import { useMemo } from "react";
import { useShownSettings } from "@/hooks/app/UseShownSettings";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { useTilted } from "@/hooks/map/UseTilted";
import { atlasLayers } from "@/logic/map/AtlasLayers";
import { useAppStore } from "@/store/AppStore";
import { MapLayers } from "./MapLayer";

/** The layers drawn from the app's vector tiles, in the View tab's look, Find's highlight and the tilt (tilted, the
 * 3D view draws paths, icons and models instead). Only what changed is set on the map. */
export function AtlasLayers() {
	const map = useMapLibre();
	const { geo, info, meta } = useMapView();
	const settings = useShownSettings(); // (with the layers you're working on: user)
	const highlight = useAppStore((s) => s.highlight);
	const tilted = useTilted(map);
	const specs = useMemo(
		() =>
			settings
				? atlasLayers(geo, info, meta, {
						settings,
						background: settings.ui.background ?? "picture",
						tilted,
						highlight,
					})
				: [],
		[geo, info, meta, settings, tilted, highlight],
	);
	return <MapLayers specs={specs} />;
}
