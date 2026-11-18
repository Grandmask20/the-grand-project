import { FullscreenControl, type Map as MapLibreMap, NavigationControl, Map as MapView } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import type { Meta } from "@/domain/app/Meta";
import type { MapInfo } from "@/domain/map/MapInfo";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { Geo } from "@/logic/Geo";
import { baseStyle, squareImage } from "@/logic/MapStyle";
import { useAppStore } from "@/store/AppStore";
import { ButtonControl } from "./ButtonControl";
import { FrameRecorder } from "./FrameRecorder";
import { MapCamera } from "./MapCamera";
import { MapIcons } from "./MapIcons";
import { MapImages } from "./MapImages";
import { MapInteraction } from "./MapInteraction";
import { MapLabels } from "./MapLabels";
import { MapLook } from "./MapLook";
import { MapOverlays } from "./MapOverlays";
import { MapTiles, vectorVersion } from "./MapTiles";
import { PlayerMarker } from "./PlayerMarker";
import { ReplayLayers } from "./ReplayLayers";

interface Props {
	info: MapInfo;
	meta: Meta;
}

/** The map: MapLibre on the app's tiles, with everything the page draws over them. */
export function AtlasMap({ info, meta }: Props) {
	const app = useAppClient();
	const box = useRef<HTMLDivElement>(null);
	const [map, setMap] = useState<MapLibreMap | null>(null);
	const [geo] = useState(() => new Geo(info));
	const setStoreMap = useAppStore((s) => s.setMap);

	// biome-ignore lint/correctness/useExhaustiveDependencies: made once per grid (the parent remounts on a new one)
	useEffect(() => {
		if (!box.current) return;
		const [[w, s], [e, n]] = info.bounds;
		const padX = (e - w) * 0.35;
		const padY = (n - s) * 0.35;
		const cam = useAppStore.getState().camera;
		const m = new MapView({
			container: box.current,
			style: baseStyle(info, geo, meta, app.terrainTiles(info.terrain_version), app.vectorTiles(vectorVersion(info))),
			bounds: cam ? undefined : info.bounds,
			center: cam ? geo.toLngLat(cam.x, cam.y) : undefined,
			zoom: cam ? geo.zoomFor(cam.px) : undefined,
			bearing: cam?.bearing ?? 0,
			pitch: cam?.pitch ?? 0,
			fitBoundsOptions: { padding: 30 },
			maxBounds: [
				[w - padX, s - padY],
				[e + padX, n + padY],
			],
			maxZoom: info.maxzoom,
			maxPitch: 75,
			renderWorldCopies: false,
			attributionControl: false,
			doubleClickZoom: false,
		});
		m.addControl(new NavigationControl({ visualizePitch: true }), "top-right");
		m.addControl(
			new ButtonControl("⤢", "Fit the whole atlas (0)", () => m.fitBounds(info.bounds, { padding: 30 })),
			"top-right",
		);
		const three = new ButtonControl("3D", "3D view (or right-drag / Ctrl-drag to tilt and turn)", () => {
			if (m.getPitch() > 1) m.easeTo({ pitch: 0, bearing: 0, duration: 700 });
			else m.easeTo({ pitch: 60, bearing: m.getBearing() || -20, duration: 700 });
		});
		m.addControl(three, "top-right");
		m.addControl(new FullscreenControl(), "top-right");
		m.on("pitch", () => three.setOn(m.getPitch() > 1));
		m.on("load", () => {
			if (!m.hasImage("node-square")) m.addImage("node-square", squareImage(), { sdf: true });
			setMap(m);
			setStoreMap(m);
		});
		return () => {
			setStoreMap(null);
			setMap(null);
			m.remove();
		};
	}, []);

	return (
		<div className="relative h-full w-full" data-testid="atlas-map">
			<div ref={box} className="absolute inset-0" />
			{map && (
				<>
					<MapTiles map={map} />
					<MapLook map={map} geo={geo} meta={meta} />
					<MapIcons map={map} geo={geo} info={info} />
					<MapCamera map={map} geo={geo} info={info} />
					<MapOverlays map={map} geo={geo} />
					<MapImages map={map} geo={geo} />
					<ReplayLayers map={map} geo={geo} meta={meta} />
					<MapInteraction map={map} geo={geo} meta={meta} />
					<MapLabels map={map} meta={meta} />
					<PlayerMarker map={map} geo={geo} />
					<FrameRecorder map={map} />
				</>
			)}
		</div>
	);
}
