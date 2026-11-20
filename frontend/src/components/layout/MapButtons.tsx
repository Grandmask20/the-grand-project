import {
	BoxIcon,
	CompassIcon,
	type LucideIcon,
	MaximizeIcon,
	MinimizeIcon,
	ScanIcon,
	ZoomInIcon,
	ZoomOutIcon,
} from "lucide-react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useState } from "react";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/**
 * The game's own atlas camera, for the 3D button: facing north, tilted so the ground's vanishing line sits where the
 * program measured it (core HORIZON: 2155 px above a 1080p screenshot's top, 2695 px above its middle). With
 * MapLibre's lens (36.87 deg high: a 1620 px focal length on 1080 px) that is atan(2695 / 1620) = 59 deg from straight
 * down. (It turned the map by -20 deg unless already turned, so it landed on different views: user.)
 */
export const GAME_PITCH = 59;

/** Whether the map is tilted, as it tilts (the 3D button lights up during the tilt, not only after it). */
function useTilted(map: MapLibreMap | null): boolean {
	const [tilted, setTilted] = useState(false);
	useEffect(() => {
		if (!map) return;
		const onPitch = () => setTilted(map.getPitch() > 1);
		onPitch();
		map.on("pitch", onPitch);
		return () => {
			map.off("pitch", onPitch);
		};
	}, [map]);
	return !!map && tilted;
}

/** Whether the page is full screen (the browser's own Esc leaves it too). */
function useFullScreen(): boolean {
	const [full, setFull] = useState(() => !!document.fullscreenElement);
	useEffect(() => {
		const onChange = () => setFull(!!document.fullscreenElement);
		document.addEventListener("fullscreenchange", onChange);
		return () => document.removeEventListener("fullscreenchange", onChange);
	}, []);
	return full;
}

function MapButton({
	Icon,
	label,
	onClick,
	on,
	disabled,
}: {
	Icon: LucideIcon;
	label: string;
	onClick: () => void;
	on?: boolean;
	disabled: boolean;
}) {
	return (
		<button
			type="button"
			aria-label={label}
			title={label}
			aria-pressed={on}
			disabled={disabled}
			onClick={onClick}
			className={cn(
				"flex h-6 w-7 items-center justify-center rounded disabled:opacity-40",
				on ? "bg-gold text-background" : "text-muted-foreground hover:bg-accent hover:text-foreground",
			)}
		>
			<Icon className="size-3.5" aria-hidden />
		</button>
	);
}

/**
 * The map's camera in the status line (PO: no controls over the map): zoom, fit the whole atlas, face north, the 3D
 * view (the game's own camera) and full screen. They were MapLibre's controls on the map's top right.
 */
export function MapButtons() {
	const map = useAppStore((s) => s.map);
	const requestFit = useAppStore((s) => s.requestFit);
	const tilted = useTilted(map);
	const full = useFullScreen();
	const none = !map;
	const zoom = (by: number) => map?.easeTo({ zoom: map.getZoom() + by, duration: 250 });
	const tilt = () =>
		map?.easeTo(
			map.getPitch() > 1 ? { pitch: 0, bearing: 0, duration: 700 } : { pitch: GAME_PITCH, bearing: 0, duration: 700 },
		);
	const fullScreen = () =>
		void (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()).catch(
			() => undefined, // (refused by the browser: nothing changes)
		);
	return (
		<fieldset aria-label="Map view" className="m-0 flex min-w-0 items-center gap-0.5 border-0 p-0">
			<MapButton Icon={ZoomOutIcon} label="Zoom out" onClick={() => zoom(-1)} disabled={none} />
			<MapButton Icon={ZoomInIcon} label="Zoom in" onClick={() => zoom(1)} disabled={none} />
			<MapButton Icon={ScanIcon} label="Fit the whole atlas (0)" onClick={requestFit} disabled={none} />
			<MapButton
				Icon={CompassIcon}
				label="Face north"
				onClick={() => map?.easeTo({ bearing: 0, duration: 400 })}
				disabled={none}
			/>
			<MapButton
				Icon={BoxIcon}
				label="3D view (or right-drag / Ctrl-drag to tilt and turn)"
				onClick={tilt}
				on={tilted}
				disabled={none}
			/>
			<MapButton
				Icon={full ? MinimizeIcon : MaximizeIcon}
				label={full ? "Leave full screen" : "Full screen"}
				onClick={fullScreen}
				on={full}
				disabled={false}
			/>
		</fieldset>
	);
}
