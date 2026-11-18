/** A label to place on the map: its anchor on screen and its text. */
export interface LabelCandidate {
	key: string;
	x: number;
	y: number;
	text: string;
	colour: string;
	priority: number;
}

export interface PlacedLabel extends LabelCandidate {
	left: number;
	top: number;
	width: number;
}

const CHAR_W = 6.6; // px per character at the labels' font size
const H = 16;
const CELL = 64;

/** Places labels above their anchors, most important first, leaving out those that would overlap a placed one. */
export function placeLabels(cands: LabelCandidate[], width: number, height: number, max = 400): PlacedLabel[] {
	const grid = new Map<string, [number, number, number, number][]>();
	const out: PlacedLabel[] = [];
	const sorted = [...cands].sort((a, b) => b.priority - a.priority);
	for (const c of sorted) {
		if (out.length >= max) break;
		const w = Math.min(260, c.text.length * CHAR_W + 8);
		const left = c.x - w / 2;
		const top = c.y - H - 10;
		if (left + w < 0 || top + H < 0 || left > width || top > height) continue;
		const box: [number, number, number, number] = [left, top, left + w, top + H];
		const cells = cellsOf(box);
		if (cells.some((k) => grid.get(k)?.some((b) => overlaps(b, box)))) continue;
		for (const k of cells) {
			const list = grid.get(k);
			if (list) list.push(box);
			else grid.set(k, [box]);
		}
		out.push({ ...c, left, top, width: w });
	}
	return out;
}

function cellsOf([x0, y0, x1, y1]: [number, number, number, number]): string[] {
	const keys: string[] = [];
	for (let i = Math.floor(x0 / CELL); i <= Math.floor(x1 / CELL); i++)
		for (let j = Math.floor(y0 / CELL); j <= Math.floor(y1 / CELL); j++) keys.push(`${i},${j}`);
	return keys;
}

function overlaps(a: [number, number, number, number], b: [number, number, number, number]): boolean {
	return a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
}
