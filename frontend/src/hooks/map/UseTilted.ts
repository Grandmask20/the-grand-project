import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";

/** Whether the map is tilted (the 3D view), as of its last tilt's end. */
export function useTilted(map: MapLibreMap): boolean {
	const [tilted, setTilted] = useState(() => map.getPitch() > 1);
	useEffect(() => {
		const onPitch = () => setTilted(map.getPitch() > 1);
		map.on("pitchend", onPitch);
		return () => {
			map.off("pitchend", onPitch);
		};
	}, [map]);
	return tilted;
}
