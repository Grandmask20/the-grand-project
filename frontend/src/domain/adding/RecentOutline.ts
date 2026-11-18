/** A recently added screenshot's outline (age 0 = newest). */
export interface RecentOutline {
	name: string;
	corners: [number, number][];
	age: number;
	picked: boolean;
}
