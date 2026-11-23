import type { SharedAtlas } from "@/domain/share/SharedAtlas";
import { mapInfo } from "./Fixtures";

/** A friend's atlas as live sharing sends it: three maps, two paths (one curved), a landmark. */
export const sharedAtlas: SharedAtlas = {
	name: "nyx atlas",
	info: mapInfo,
	nodes: [
		{ id: 1, x: 0, y: 0, icons: ["Breach", "Breach", "Ritual"], status: "confirmed" },
		{ id: 2, x: 100, y: 0, icons: [], status: "confirmed" },
		{ id: 3, x: 200, y: 50, icons: ["Abyss"], status: "seen once" },
	],
	edges: [
		{
			a: 1,
			b: 2,
			line: [
				[0, 0],
				[50, 10],
				[100, 0],
			],
		},
		{ a: 2, b: 3 },
	],
	landmarks: [{ id: 0, x: 200, y: 60, kind: "Vaal city", label: "Vaal city", node: 3 }],
};
