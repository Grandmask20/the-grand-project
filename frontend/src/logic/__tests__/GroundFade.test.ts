import { describe, expect, it } from "vitest";
import { GroundFade } from "@/logic/GroundFade";
import { fakeGl } from "@/test/FakeGl";
import { fakeMap } from "@/test/FakeMap";

const frame = {
	defaultProjectionData: { mainMatrix: new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) },
} as never;

describe("GroundFade", () => {
	it("is a sheet over the world fading to black from `far` times the centre's distance", () => {
		const { map } = fakeMap();
		const { gl, called } = fakeGl();
		const fade = new GroundFade(2.4);
		expect(fade).toMatchObject({ id: "ground-fade-gl", type: "custom", renderingMode: "3d" });
		fade.onAdd(map as never, gl);
		fade.render(gl, frame);
		expect(called("drawArrays")).toHaveLength(1);
		fade.onRemove(map as never, gl);
		expect(called("deleteProgram")).toHaveLength(1);
	});
});
