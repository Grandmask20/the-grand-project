/**
 * Plain symbols for a bookmark's or a group's look (user: "utf icons and or poe icons", like the game's own map
 * markers): simple shapes drawn in the look's colour, with no ring. Each is a path in a 24 x 24 box; an icon named
 * `sym:<name>` is one of them.
 */
export const SYMBOLS: Record<string, string> = {
	triangle: "M12 3 L22 20 L2 20 Z",
	diamond: "M12 2 L21 12 L12 22 L3 12 Z",
	sparkle: "M12 2 C13 8 16 11 22 12 C16 13 13 16 12 22 C11 16 8 13 2 12 C8 11 11 8 12 2 Z",
	star: "M12 2 L14.9 8.6 L22 9.3 L16.6 14 L18.2 21 L12 17.3 L5.8 21 L7.4 14 L2 9.3 L9.1 8.6 Z",
	circle: "M12 3 A9 9 0 1 1 11.99 3 Z",
	square: "M4 4 H20 V20 H4 Z",
	hexagon: "M12 2 L21 7 L21 17 L12 22 L3 17 L3 7 Z",
	cross: "M9 3 H15 V9 H21 V15 H15 V21 H9 V15 H3 V9 H9 Z",
	heart:
		"M12 21 C5 15 2 12 2 8 C2 5 4.5 3 7 3 C9 3 11 4.5 12 6 C13 4.5 15 3 17 3 C19.5 3 22 5 22 8 C22 12 19 15 12 21 Z",
	flag: "M5 2 H7 V22 H5 Z M7 3 H19 L16 7.5 L19 12 H7 Z",
	crown: "M3 18 L4 7 L9 11 L12 4 L15 11 L20 7 L21 18 Z",
	bolt: "M13 2 L4 14 H11 L10 22 L20 9 H13 Z",
	skull:
		"M12 2 C7 2 4 5.5 4 10 C4 13 5.5 15 7 16 V20 H9 V18 H11 V20 H13 V18 H15 V20 H17 V16 C18.5 15 20 13 20 10 C20 5.5 17 2 12 2 Z M8.5 7.5 A2 2 0 1 1 8.49 7.5 Z M15.5 7.5 A2 2 0 1 1 15.49 7.5 Z",
};

const PREFIX = "sym:";

/** Whether a look's icon is one of the symbols (else a map icon's or a place's picture). */
export const isSymbol = (icon: string | undefined): boolean =>
	!!icon && icon.startsWith(PREFIX) && icon.slice(PREFIX.length) in SYMBOLS;

/** A symbol's path ("" when it isn't one). */
export const symbolPath = (icon: string): string => (isSymbol(icon) ? SYMBOLS[icon.slice(PREFIX.length)] : "");

/** The map's picture name of a symbol in a colour (each colour its own picture: symbolImage draws it). */
export const symbolImageId = (icon: string, colour: string): string => `${icon}:${colour}`;

/** The picture the map draws for `sym:<name>:<colour>`: the symbol in its colour, edged in black, 64 px (as the map
 * icons' pictures, so they take the same size). Null when it isn't one, or without a canvas. */
export function symbolImage(id: string, px = 64): { width: number; height: number; data: Uint8Array } | null {
	const at = id.lastIndexOf(":");
	const icon = id.slice(0, at);
	const colour = id.slice(at + 1);
	const path = symbolPath(icon);
	if (!path || typeof document === "undefined") return null;
	const canvas = document.createElement("canvas");
	canvas.width = px;
	canvas.height = px;
	const g = canvas.getContext("2d");
	if (!g || typeof Path2D === "undefined") return null;
	g.scale(px / 24, px / 24);
	const shape = new Path2D(path);
	g.lineJoin = "round";
	g.lineWidth = 2;
	g.strokeStyle = "rgba(0,0,0,0.85)";
	g.stroke(shape);
	g.fillStyle = colour;
	g.fill(shape, "evenodd");
	return { width: px, height: px, data: new Uint8Array(g.getImageData(0, 0, px, px).data.buffer) };
}
