import { useEffect } from "react";
import { useMapLibre } from "@/hooks/map/UseMapLibre";
import { useAppStore } from "@/store/AppStore";

/**
 * Panning (left-drag, MapLibre's own drag pan off): the mouse's movement in px moves the map at the scale of the
 * view's centre. MapLibre's own drag keeps the grabbed ground point under the mouse, which near the horizon moved
 * further and further with every px (user: it sped up endlessly). Not while drawing a lasso or moving a screenshot
 * placed by hand, nor with Ctrl (tilt and turn).
 */
export function MapPan() {
	const map = useMapLibre();

	useEffect(() => {
		const canvas = map.getCanvasContainer();
		let last: [number, number] | null = null;
		const down = (e: MouseEvent) => {
			const kind = useAppStore.getState().mode.kind;
			if (e.button !== 0 || e.ctrlKey || kind === "lasso" || kind === "ghost") return;
			last = [e.clientX, e.clientY];
		};
		const move = (e: MouseEvent) => {
			if (!last || !(e.buttons & 1)) {
				last = null;
				return;
			}
			const dx = e.clientX - last[0];
			const dy = e.clientY - last[1];
			last = [e.clientX, e.clientY];
			if (dx || dy) map.panBy([-dx, -dy], { animate: false });
		};
		const up = () => {
			last = null;
		};
		canvas.addEventListener("mousedown", down);
		window.addEventListener("mousemove", move);
		window.addEventListener("mouseup", up);
		return () => {
			canvas.removeEventListener("mousedown", down);
			window.removeEventListener("mousemove", move);
			window.removeEventListener("mouseup", up);
		};
	}, [map]);

	return null;
}
