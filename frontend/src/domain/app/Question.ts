/** Where a screenshot would be added: a see-through picture (GET /api/pictures/{picture}.png) over an atlas box. */
export interface Preview {
	picture: number;
	box: [number, number, number, number];
}

/** A yes / no question from the app (a weak match, a crowded folder, ...). */
export interface Question {
	id: number;
	question: string;
	preview: Preview | null;
}
