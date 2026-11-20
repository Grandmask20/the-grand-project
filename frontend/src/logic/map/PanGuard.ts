/** Whether the last press on the map was a drag (a pan), not a click. Panning is the page's own (MapPan), so
 * MapLibre still reported a press that was dragged and let go as a click (user: in Route, a pan after the first map
 * took the map nearest where it ended; a pan cleared the selection). */
let from: [number, number] | null = null;
let far = 0;

/** A press on the map began here (screen px). */
export function pressAt(x: number, y: number): void {
	from = [x, y];
	far = 0;
}

/** The mouse is here while pressed. */
export function pressMove(x: number, y: number): void {
	if (from) far = Math.max(far, Math.hypot(x - from[0], y - from[1]));
}

/** The last press moved further than a click's wobble. */
export function wasDrag(): boolean {
	return far > PAN_CLICK_PX;
}

/** How far (screen px) a press may move and still be a click. */
export const PAN_CLICK_PX = 4;
