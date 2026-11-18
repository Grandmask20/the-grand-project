/** Where a screenshot would be added: a see-through picture (GET /api/pictures/{picture}.png) over an atlas box. */
export interface Preview {
	picture: number;
	box: [number, number, number, number];
	/** The atlas map nodes its own map nodes land on (the maps the question says agree): ringed on the map. */
	agree?: [number, number][];
	/** What it joins (those maps and the screenshot its terrain was compared with, else the placed screenshots nearest to it (x0, y0, x1, y1): shown with it, so you see what it joins (or the gap). */
	near?: [number, number, number, number] | null;
}

/** A yes / no question from the app (a weak match, a crowded folder, ...). */
export interface Question {
	id: number;
	question: string;
	preview: Preview | null;
}
