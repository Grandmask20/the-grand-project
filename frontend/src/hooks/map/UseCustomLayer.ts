import type { CustomLayerInterface } from "maplibre-gl";
import { useEffect, useState } from "react";
import type { LayerId } from "@/logic/map/LayerOrder";
import { slotOf } from "@/logic/map/LayerOrder";
import { mapAlive, useMapLibre } from "./UseMapLibre";

/**
 * A WebGL layer of our own (the 3D view's), on the map while `on`, in its place in the stack, handed out (null while
 * off). react-map-gl's <Layer> copies a custom layer's fields into a new object, which loses a class's methods, so
 * these are added here.
 */
export function useCustomLayer<L extends CustomLayerInterface & { id: LayerId }>(on: boolean, make: () => L): L | null {
	const map = useMapLibre();
	const [layer, setLayer] = useState<L | null>(null);
	useEffect(() => {
		if (!on) return;
		const l = make();
		map.addLayer(l, slotOf(l.id));
		setLayer(l);
		return () => {
			setLayer(null);
			if (mapAlive(map) && map.getLayer(l.id)) map.removeLayer(l.id);
		};
	}, [map, on, make]);
	return layer;
}
