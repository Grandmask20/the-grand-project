import { describe, expect, it } from "vitest";
import { ModelLayer3D } from "@/logic/ModelLayer3D";
import { fakeGl } from "@/test/FakeGl";
import { fakeMap } from "@/test/FakeMap";

const frame = {
	defaultProjectionData: { mainMatrix: new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) },
} as never;
const square: [number, number][] = [
	[0, 0],
	[0.001, 0],
	[0.001, 0.001],
	[0, 0.001],
];
const model = (pick: number, step = -1) => ({
	rings: [square],
	base: 0,
	height: 20,
	colour: [1, 0.5, 0] as [number, number, number],
	anchor: [0.0005, 0.0005] as [number, number],
	step,
	pick,
});

function layer() {
	const { map } = fakeMap();
	const { gl, called } = fakeGl();
	const l = new ModelLayer3D();
	l.onAdd(map as never, gl);
	return { l, gl, called, map };
}

describe("ModelLayer3D", () => {
	it("compiles its shaders when added", () => {
		const { called } = layer();
		expect(called("compileShader")).toHaveLength(2);
		expect(called("linkProgram")).toHaveLength(1);
	});

	it("draws the models given, as extruded sides and tops", () => {
		const { l, gl, called } = layer();
		l.render(gl, frame);
		expect(called("drawArrays")).toHaveLength(0); // nothing yet
		l.setModels([model(5), model(6, 3)]);
		l.selected = 5;
		l.pos = 2;
		l.render(gl, frame);
		const [[, , count]] = called("drawArrays").map((c) => c.args);
		expect(count).toBeGreaterThan(0);
		expect((count as number) % 3).toBe(0); // whole triangles
		expect(called("bufferData")).toHaveLength(1); // uploaded once
		l.render(gl, frame);
		expect(called("bufferData")).toHaveLength(1);
	});

	it("answers a click from the next frame drawn (nothing there: 0), and none before anything is drawn", async () => {
		const { l, gl } = layer();
		await expect(l.pickAt(10, 10)).resolves.toBe(0);
		l.setModels([model(5)]);
		l.render(gl, frame);
		const answer = l.pickAt(10, 10);
		l.render(gl, frame);
		await expect(answer).resolves.toBe(0);
	});

	it("lets go of the GPU's things when taken off, and answers waiting clicks", async () => {
		const { l, gl, called } = layer();
		l.setModels([model(5)]);
		l.render(gl, frame);
		const waiting = l.pickAt(1, 1);
		l.onRemove();
		await expect(waiting).resolves.toBe(0);
		expect(called("deleteProgram")).toHaveLength(1);
	});
});
