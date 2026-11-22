import type { GeoJSONSource } from "maplibre-gl";
import { useEffect } from "react";
import { mapAlive, useMapLibre } from "@/hooks/map/UseMapLibre";
import type { LngLat } from "@/logic/Geo";
import { collection, EMPTY, point } from "@/logic/map/Features";
import { alongLine, dashAt, RUN_MS_PER_MAP } from "@/logic/RouteRun";

/** Whether the system asks for less motion: then the dashes stand still and the runner waits at the leg's end. */
const stillPlease = () =>
	typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Sets the route going: its dashes marching along it (`route-dash`) and the runner walking its leg (`route-runner`)
 * over and over, a frame at a time (the map's own calls: no React render a frame). Nothing on: both still.
 *
 * Args: `leg`: the runner's line (map coordinates, empty: no runner); `maps`: how many maps it walks (its pace);
 * `on`: the route shown.
 */
export function useRouteRun(leg: LngLat[], maps: number, on: boolean) {
	const map = useMapLibre();
	useEffect(() => {
		const runner = () => map.getSource("route-runner") as GeoJSONSource | undefined;
		const dashes = (d: number[]) => {
			if (map.getLayer("route-dash")) map.setPaintProperty("route-dash", "line-dasharray", d);
		};
		if (!on || leg.length < 2) {
			runner()?.setData(EMPTY);
			return;
		}
		if (stillPlease()) {
			runner()?.setData(collection([point(leg[leg.length - 1])]));
			return;
		}
		const period = Math.max(1, maps - 1) * RUN_MS_PER_MAP;
		const start = performance.now();
		let frame = 0;
		let lastDash: number[] | null = null;
		const tick = (now: number) => {
			if (!mapAlive(map)) return;
			const ms = now - start;
			runner()?.setData(collection([point(alongLine(leg, (ms % period) / period))]));
			const d = dashAt(ms);
			if (d !== lastDash) dashes(d);
			lastDash = d;
			frame = requestAnimationFrame(tick);
		};
		frame = requestAnimationFrame(tick);
		return () => {
			cancelAnimationFrame(frame);
			if (mapAlive(map)) runner()?.setData(EMPTY);
		};
	}, [map, leg, maps, on]);
}
