/** The maps shown and the paths between them (routes are found on it). */
export interface Graph {
	nodes: GraphNode[];
	edges: GraphEdge[];
}

export interface GraphNode {
	id: number;
	x: number;
	y: number;
	icons: string[];
	status: string;
}

export interface GraphEdge {
	a: number;
	b: number;
	line?: [number, number][];
}
