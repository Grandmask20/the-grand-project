import { useEffect, useState } from "react";
import { FullscreenControl, NavigationControl, useControl } from "react-map-gl/maplibre";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useMapView } from "@/hooks/map/UseMapView";
import { ButtonControl } from "./ButtonControl";

/**
 * The game's own atlas camera, for the 3D button: facing north, tilted so the ground's vanishing line sits where the
 * program measured it (core HORIZON: 2155 px above a 1080p screenshot's top, 2695 px above its middle). With
 * MapLibre's lens (36.87 deg high: a 1620 px focal length on 1080 px) that is atan(2695 / 1620) = 59 deg from straight
 * down. (It turned the map by -20 deg unless already turned, so it landed on different views: user.)
 */
export const GAME_PITCH = 59;

/** A one-button control on the map's top right; `on` lights it up. */
function MapButton({ text, title, onClick, on }: { text: string; title: string; onClick: () => void; on?: boolean }) {
	const ctrl = useControl(() => new ButtonControl(text, title, onClick), { position: "top-right" });
	useEffect(() => ctrl.setOnClick(onClick), [ctrl, onClick]);
	useEffect(() => ctrl.setOn(!!on), [ctrl, on]);
	return null;
}

/** Fit the whole atlas (also the 0 key). */
function FitButton() {
	const map = useMapLibre();
	const { info } = useMapView();
	return (
		<MapButton text="⤢" title="Fit the whole atlas (0)" onClick={() => map.fitBounds(info.bounds, { padding: 30 })} />
	);
}

/** The 3D view: tilted to the game's own camera, or flat again. Lit while tilted. */
function TiltButton() {
	const map = useMapLibre();
	const tilted = useTiltedNow();
	const toggle = () =>
		map.easeTo(
			map.getPitch() > 1 ? { pitch: 0, bearing: 0, duration: 700 } : { pitch: GAME_PITCH, bearing: 0, duration: 700 },
		);
	return (
		<MapButton text="3D" title="3D view (or right-drag / Ctrl-drag to tilt and turn)" onClick={toggle} on={tilted} />
	);
}

/** Whether the map is tilted, as it tilts (the 3D button lights up during the tilt, not only after it). */
function useTiltedNow(): boolean {
	const map = useMapLibre();
	const [tilted, setTilted] = useState(() => map.getPitch() > 1);
	useEffect(() => {
		const onPitch = () => setTilted(map.getPitch() > 1);
		map.on("pitch", onPitch);
		return () => {
			map.off("pitch", onPitch);
		};
	}, [map]);
	return tilted;
}

/** The map's controls on its top right: zoom and compass, fit, 3D, full screen. */
export function MapControls() {
	return (
		<>
			<NavigationControl position="top-right" visualizePitch />
			<FitButton />
			<TiltButton />
			<FullscreenControl position="top-right" />
		</>
	);
}
