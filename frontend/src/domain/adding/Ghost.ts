/** A screenshot being placed by hand: its see-through picture over a box around its centre (atlas units). */
export interface Ghost {
	picture: number;
	box: [number, number, number, number];
	name: string;
	path: string;
}
