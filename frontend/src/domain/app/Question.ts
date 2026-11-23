/** Where a screenshot would be added: a see-through picture (GET /api/pictures/{picture}.png) over an atlas box. */
export interface Preview {
	picture: number;
	box: [number, number, number, number];
	/** The atlas map nodes its own map nodes land on (the maps the question says agree): ringed on the map. */
	agree?: [number, number][];
	/** What it joins (those maps and the screenshot its terrain was compared with, else the placed screenshots nearest to it (x0, y0, x1, y1): shown with it, so you see what it joins (or the gap). */
	near?: [number, number, number, number] | null;
}

/** One change in a Re-check's list: what it is and where (atlas units). */
export interface ChoiceItem {
	text: string;
	x: number;
	y: number;
	/** Something "added", "removed", or changed ("change": moved, another kind, another biome). */
	kind?: "added" | "removed" | "change";
}

/** A group of changes to tick (Re-check: maps, paths, landmarks, towers, biomes, icons). */
export interface ChoiceGroup {
	id: string;
	name: string;
	/** How many changes it has (items lists the first of them): added + removed + changed. */
	count: number;
	added: number;
	removed: number;
	changed: number;
	items: ChoiceItem[];
	/** Ticked to begin with (your ticks from the last time). */
	ticked: boolean;
}

/** A yes / no question from the app (a weak match, a crowded folder, ...), or one with ticks (choices). */
export interface Question {
	id: number;
	question: string;
	preview: Preview | null;
	/** Its own title and buttons (default: a screenshot check, Yes / No). */
	labels?: { title?: string; yes?: string; no?: string } | null;
	/** Groups to tick (a Re-check's changes): answered by its one button with the groups ticked. */
	choices?: { groups: ChoiceGroup[] } | null;
}
