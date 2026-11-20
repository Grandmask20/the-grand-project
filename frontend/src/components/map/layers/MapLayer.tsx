import type { LayerSpecification } from "maplibre-gl";
import { Layer } from "react-map-gl/maplibre";
import { type LayerId, slotOf } from "@/logic/map/LayerOrder";

/** A layer in its place in the map's stack (LAYER_ORDER), whenever it comes. react-map-gl adds it once its source
 * is there and sets only what changed in its look. */
export function MapLayer({ spec }: { spec: LayerSpecification }) {
	return <Layer {...spec} beforeId={slotOf(spec.id as LayerId)} />;
}

/** Several layers, each in its place. */
export function MapLayers({ specs }: { specs: LayerSpecification[] }) {
	return specs.map((s) => <MapLayer key={s.id} spec={s} />);
}
