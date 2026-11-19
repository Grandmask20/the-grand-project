import type { MapMode } from "@/store/AppStore";

/** What to do in a map mode (the status line, and the note over the map), or "" in the normal mode. */
export function modeHint(mode: MapMode): string {
	switch (mode.kind) {
		case "lasso":
			return "Biome select: draw around the maps (hold the left button); Esc cancels";
		case "bookmark":
			return "Click a map, or a spot, for the new bookmark; Esc cancels";
		case "player":
			return "Click the map you are on; Esc cancels";
		case "ghost":
			return "Drag the screenshot roughly where it belongs, then Enter or double-click; Esc cancels";
		case "debug-link":
			return "Debug: now click the map this one should have a path to";
		case "route":
			return mode.from === null
				? "Route: click the map it starts from; Esc cancels"
				: `Route from map #${mode.from}: now click the map it goes to; Esc cancels`;
		case "route-edit":
			return "Adjust route: click a map to add it (off the route's side: a branch), right-click one to take it off with the rest of its leg; Esc when done";
		default:
			return "";
	}
}

/** The mouse pointer over the map in a mode: a pin to place a bookmark (user: the "copy" pointer didn't say what a
 * click does), a cross to draw or pick, a hand to drag. */
export function modeCursor(mode: MapMode): string {
	switch (mode.kind) {
		case "normal":
			return "";
		case "ghost":
			return "move";
		case "bookmark":
			return `url("data:image/svg+xml,${encodeURIComponent(PIN)}") 12 30, crosshair`;
		default:
			return "crosshair";
	}
}

// a gold map pin, its point at the bottom middle (12, 30)
const PIN =
	'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="32" viewBox="0 0 24 32">' +
	'<path d="M12 31C12 31 2 18.5 2 11a10 10 0 0 1 20 0c0 7.5-10 20-10 20z" fill="#e3b341" stroke="#1a1a1a" ' +
	'stroke-width="2"/><circle cx="12" cy="11" r="3.5" fill="#1a1a1a"/></svg>';
