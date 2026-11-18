/** Find's type list: Places, then Map icons. */
export interface TypeList {
	sections: TypeSection[];
}

export interface TypeSection {
	title: string;
	rows: TypeRow[];
}

export interface TypeRow {
	label: string;
	count: number;
	icon: string;
	shown: boolean;
	aliases: string;
}
