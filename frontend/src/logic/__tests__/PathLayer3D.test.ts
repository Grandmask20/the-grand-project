import { describe, expect, it } from "vitest";
import { PathLayer3D } from "@/logic/PathLayer3D";
import { fakeGl } from "@/test/FakeGl";
import { fakeMap } from "@/test/FakeMap";

const frame = {
	defaultProjectionData: { mainMatrix: new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) },
} as never;
const path = (id: number, step = -1) => ({
	id,
	pts: [
		[0, 0],
		[0.001, 0],
		[0.002, 0.001],
	] as [number, number][],
	colour: [0, 1, 1] as [number, number, number],
	step,
});

function layer() {
	const { map } = fakeMap();
	const { gl, called } = fakeGl();
	const l = new PathLayer3D(1e-4);
	l.onAdd(map as never, gl);
	return { l, gl, called };
}

describe("PathLayer3D", () => {
	it("draws the paths given as raised ribbons, dashed as asked", () => {
		const { l, gl, called } = layer();
		l.setPaths([path(1), path(2, 4)]);
		l.dash = [12, 8];
		l.width = 3;
		l.lift = 5;
		l.render(gl, frame);
		const draws = called("drawArrays");
		expect(draws.length).toBeGreaterThan(0);
		expect(draws[0].args[2]).toBeGreaterThan(0);
		expect(called("compileShader")).toHaveLength(2);
	});

	it("draws nothing without paths, and a click there finds none", async () => {
		const { l, gl, called } = layer();
		l.setPaths([]);
		l.render(gl, frame);
		expect(called("drawArrays")).toHaveLength(0);
		await expect(l.pickAt(5, 5)).resolves.toBeNull();
	});

	it("answers a click from the next frame drawn", async () => {
		const { l, gl } = layer();
		l.setPaths([path(1)]);
		l.render(gl, frame);
		const answer = l.pickAt(5, 5);
		l.render(gl, frame);
		await expect(answer).resolves.toBeNull(); // (the fake GPU drew nothing there)
		l.onRemove();
	});
});
