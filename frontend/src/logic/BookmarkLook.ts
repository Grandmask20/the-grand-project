/** A look: a colour, an icon (each "" or missing for none) and "plain" (its icon drawn without a ring). */
export interface Look {
	colour?: string;
	icon?: string;
	plain?: boolean;
}

/**
 * A bookmark's look as it is drawn (the map, its row, the picker's preview: one rule, they each had their own:
 * CodeRabbit): its own colour and icon, else its group's; its ring as it chose when it chose a colour of its own (a
 * colour, or "none"), else as its group chose, whichever icon it shows.
 */
export function bookmarkLook(b: Look, g: Look): { colour: string; icon: string; plain: boolean } {
	const ownRing = !!(b.colour || b.plain);
	return { colour: b.colour || g.colour || "", icon: b.icon || g.icon || "", plain: ownRing ? !!b.plain : !!g.plain };
}
