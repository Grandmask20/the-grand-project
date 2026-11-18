/** Debug marks (internal copy only). */
export interface DebugMarks {
	enabled: boolean;
	marks: DebugMark[];
	reasons: Record<string, string[]>;
	file: string;
}

export interface DebugMark {
	id: number;
	time: string;
	kind: string;
	reason: string;
	note: string;
	x: number;
	y: number;
	maps: { id: number; x: number; y: number }[];
	path?: { ends: [[number, number], [number, number]] };
	screenshots: string[];
}

export interface DebugMarkDraft {
	kind: string;
	reason: string;
	note: string;
	x?: number;
	y?: number;
	maps?: number[];
	path?: number;
}
