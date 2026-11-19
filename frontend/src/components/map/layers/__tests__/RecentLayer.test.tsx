import { waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RecentLayer } from "@/components/map/layers/RecentLayer";
import { features, renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const box: [number, number][] = [
	[0, 0],
	[10, 0],
	[10, 10],
	[0, 10],
];

describe("RecentLayer", () => {
	it("outlines the screenshots added last, fading with their age", async () => {
		const recent = [
			{ name: "a", corners: box, age: 0, picked: false },
			{ name: "b", corners: box, age: 1, picked: true },
			{ name: "c", corners: box, age: 2, picked: false },
		];
		const { fm } = renderOnMap(<RecentLayer />, { "GET /api/recent": recent });
		await waitFor(() => expect(features(fm, "recent")).toHaveLength(3));
		const props = features(fm, "recent").map((f) => f.properties);
		expect(props.map((p) => p?.opacity)).toEqual([1, 1, 1 - 2 / 4]); // the picked one stays bright
		expect(fm.layers[0]).toMatchObject({ id: "recent", before: "slot:recent" });
	});
});
