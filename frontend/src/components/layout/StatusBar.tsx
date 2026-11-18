import type { MapMouseEvent } from "maplibre-gl";
import { useEffect, useState } from "react";
import { useAppState } from "@/hooks/app/UseAppState";
import { useGeo } from "@/hooks/map/UseGeo";
import { useAppStore } from "@/store/AppStore";

/** The status line, the mode's hint, and where the mouse is on the atlas. */
export function StatusBar({ connected }: { connected: boolean }) {
	const state = useAppState().data;
	const map = useAppStore((s) => s.map);
	const mode = useAppStore((s) => s.mode);
	const geo = useGeo();
	const [at, setAt] = useState<string>("");

	useEffect(() => {
		if (!map || !geo) return;
		const move = (e: MapMouseEvent) => {
			const [x, y] = geo.toAtlas(e.lngLat.lng, e.lngLat.lat);
			setAt(`x ${x.toFixed(0)}  y ${y.toFixed(0)}   zoom ${geo.pxPerUnit(map.getZoom()).toFixed(2)}`);
		};
		map.on("mousemove", move);
		return () => {
			map.off("mousemove", move);
		};
	}, [map, geo]);

	const hint =
		mode.kind === "lasso"
			? "draw around the maps of the biome (hold the left button); Esc cancels"
			: mode.kind === "bookmark"
				? "click where the bookmark goes; Esc cancels"
				: mode.kind === "player"
					? "click the map you are on; Esc cancels"
					: mode.kind === "ghost"
						? "drag the screenshot roughly where it belongs, then Enter or double-click; Esc cancels"
						: mode.kind === "debug-link"
							? "debug: now click the map this one should have a path to"
							: "";

	return (
		<footer className="flex h-7 shrink-0 items-center gap-4 border-t bg-card px-3 font-mono text-xs text-muted-foreground">
			{!connected && <span className="text-destructive">not connected to the app</span>}
			<span className="truncate text-foreground">{hint || state?.status}</span>
			<span className="flex-1" />
			{state?.busy && <span className="text-gold">working…</span>}
			<span>{at}</span>
		</footer>
	);
}
