import { act, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Scene3D } from "@/components/map/three/Scene3D";
import type { IconLayer3D } from "@/logic/IconLayer3D";
import type { ModelLayer3D } from "@/logic/ModelLayer3D";
import { useAppStore } from "@/store/AppStore";
import { mapInfo, state } from "@/test/Fixtures";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

const scene = {
	icons: [[10, 20, 3, "Breach", 0, 5, -1, 12]],
	paths: [
		{
			id: 7,
			strong: true,
			abyss: false,
			share: 0.9,
			step: -1,
			pts: [
				[0, 0],
				[10, 0],
			],
		},
		{
			id: 8,
			strong: false,
			abyss: false,
			share: 0.2,
			step: -1,
			pts: [
				[0, 0],
				[0, 10],
			],
		},
		{
			id: 9,
			strong: false,
			abyss: true,
			share: 0.1,
			step: -1,
			pts: [
				[0, 0],
				[5, 5],
			],
		},
	],
	models: [
		{
			rings: [
				[
					[0, 0],
					[1, 0],
					[1, 1],
				],
			],
			colour: "#ff8c1a",
			base: 0,
			height: 10,
			ax: 0,
			ay: 0,
			step: -1,
			pick: "node:12",
		},
		{
			rings: [
				[
					[5, 5],
					[6, 5],
					[6, 6],
				],
			],
			colour: "#cccccc",
			base: 0,
			height: 10,
			ax: 5,
			ay: 5,
			step: -1,
			pick: "",
		},
	],
};

/** The app with a map image (the scene is fetched per version of it). */
const app = (st = state) => ({ "GET /api/scene3d": scene, "GET /api/state": { ...st, map: mapInfo } });
const tilt = () => act(() => useAppStore.setState({ camera: { x: 0, y: 0, px: 1, bearing: 0, pitch: 59 } }));
const impl = <T,>(fm: ReturnType<typeof renderOnMap>["fm"], id: string) =>
	fm.layers.find((l) => l.id === id)?.spec as unknown as T | undefined;

describe("Scene3D", () => {
	it("flat: no 3D layers", () => {
		const { fm } = renderOnMap(<Scene3D />, app());
		expect(fm.drawn()).toEqual([]);
	});

	it("tilted: models, paths, icons and the ground fading out, each in its slot, given the scene", async () => {
		const { fm } = renderOnMap(<Scene3D />, app());
		tilt();
		await waitFor(() =>
			expect(fm.layerIds().sort()).toEqual(["ground-fade-gl", "icons-3d-gl", "models-3d-gl", "paths-3d-gl"]),
		);
		for (const l of fm.drawn()) expect(l.before).toBe(`slot:${l.id}`);
		// (what each was given, before it is uploaded)
		const models = impl<{ pending: unknown[] }>(fm, "models-3d-gl");
		await waitFor(() => expect(models?.pending).toHaveLength(2));
		const paths = impl<{ pending: unknown[] }>(fm, "paths-3d-gl");
		await waitFor(() => expect(paths?.pending).toHaveLength(3)); // drawn by at least 0: every path
		expect(impl<IconLayer3D>(fm, "icons-3d-gl")?.models).toBe(true);
	});

	it('hides the paths drawn by fewer screenshots than "drawn by at least" (Abyss chains always shown)', async () => {
		const settings = { ...state.settings, style: { ...state.settings.style, path_freq: 0.5 } };
		const { fm } = renderOnMap(<Scene3D />, app({ ...state, settings }));
		tilt();
		await waitFor(() =>
			expect(impl<{ pending: { id: number }[] }>(fm, "paths-3d-gl")?.pending.map((p) => p.id)).toEqual([7, 9]),
		);
	});

	it("beams off: the beams' models are left out", async () => {
		const settings = { ...state.settings, style: { ...state.settings.style, d3_beams: false } };
		const { fm } = renderOnMap(<Scene3D />, app({ ...state, settings }));
		tilt();
		await waitFor(() => expect(impl<{ pending: unknown[] }>(fm, "models-3d-gl")?.pending).toHaveLength(1));
	});

	it("lights the selection up and follows the timelapse", async () => {
		const { fm } = renderOnMap(<Scene3D />, app());
		tilt();
		await waitFor(() => expect(fm.drawn()).toHaveLength(4));
		act(() => {
			useAppStore.setState({ selected: { kind: "icon", id: 3, x: 0, y: 0 } as never });
			useAppStore.setState({ replay: { pos: 2, plan: {} } as never });
		});
		expect(impl<IconLayer3D>(fm, "icons-3d-gl")?.selected).toBe(3);
		expect(impl<ModelLayer3D>(fm, "models-3d-gl")?.pos).toBe(2);
		expect(fm.map.triggerRepaint).toHaveBeenCalled();
	});

	it("3D models off: none, and the icons no longer stand on them", async () => {
		const settings = { ...state.settings, layers: { ...state.settings.layers, "3D models": false } };
		const { fm } = renderOnMap(<Scene3D />, app({ ...state, settings }));
		tilt();
		await waitFor(() => expect(fm.layerIds()).toContain("icons-3d-gl"));
		expect(fm.layerIds()).not.toContain("models-3d-gl");
		expect(impl<IconLayer3D>(fm, "icons-3d-gl")?.models).toBe(false);
	});

	it("flat again: the layers go", async () => {
		const { fm } = renderOnMap(<Scene3D />, app());
		tilt();
		await waitFor(() => expect(fm.drawn()).toHaveLength(4));
		act(() => useAppStore.setState({ camera: { x: 0, y: 0, px: 1, bearing: 0, pitch: 0 } }));
		expect(fm.drawn()).toEqual([]);
	});
});
