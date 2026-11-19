/** GET /api/frames: every screenshot's outline, session and age, with the colours "Colour by" uses. */
export interface Frames {
	frames: FrameInfo[];
	order: number[];
	ramp: string[];
	sessions: string[];
	legend: { label: string; colour: string }[];
	oldest: string;
	newest: string;
	alpha: number;
	heat_top: number;
}

export interface FrameInfo {
	name: string;
	corners: [number, number][];
	session: number;
	rank: number;
	time: number | null;
}
