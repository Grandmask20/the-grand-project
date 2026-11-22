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
	/** The map node's state (grey / blue / green / red, named by finalize.states; "" or left out when no screenshot
	 * named it): routes never run green or red maps. */
	state?: string;
}

export interface GraphEdge {
	a: number;
	b: number;
	line?: [number, number][];
}
