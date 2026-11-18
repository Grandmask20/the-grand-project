/** A screenshot that shows a spot (px, py: the spot in its pixels). */
export interface SourceShot {
	name: string;
	w: number;
	h: number;
	px: number;
	py: number;
	exists: boolean;
}
