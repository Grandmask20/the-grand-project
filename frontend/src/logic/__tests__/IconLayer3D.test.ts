import { describe, expect, it, vi } from "vitest";
import { IconLayer3D } from "@/logic/IconLayer3D";
import { fakeGl, settled } from "@/test/FakeGl";
import { fakeMap } from "@/test/FakeMap";

const frame = {
	defaultProjectionData: { mainMatrix: new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]) },
} as never;
const icon = (id: number, name: string, slot = 0, step = -1) => ({
	lng: 0.001 * id,
	lat: 0,
	atlas: [id, 0] as [number, number],
	id,
	name,
	slot,
	lift: 0,
	step,
});
const picture = () => {
	const c = document.createElement("canvas");
	c.width = c.height = 64;
	return c;
};

function layer(load = vi.fn(async (_name: string) => picture() as CanvasImageSource | null)) {
	const { map } = fakeMap();
	const { gl, called, draws } = fakeGl();
	const l = new IconLayer3D(1e-4, load);
	l.onAdd(map as never, gl);
	return { l, gl, called, draws, load, map };
}

describe("IconLayer3D", () => {
	it("fetches each picture once and draws the icons standing in their rows", async () => {
		const { l, gl, called, load } = layer();
		await l.setIcons([icon(1, "Breach"), icon(2, "Breach", 1), icon(3, "Ritual", 0, 2)]);
		expect(load.mock.calls.map((c) => c[0]).sort()).toEqual(["Breach", "Ritual"]);
		l.selected = 2;
		l.pos = 3;
		l.render(gl, frame);
		expect(called("drawArrays")[0]?.args[2]).toBe(18); // 3 icons, 2 triangles each
		expect(called("texImage2D").length).toBeGreaterThan(0); // their pictures, in one texture
		await l.setIcons([icon(4, "Breach")]);
		expect(load).toHaveBeenCalledTimes(2); // known already
	});

	it("an older set whose pictures come in late is never drawn over a newer one", async () => {
		const later: Record<string, (c: CanvasImageSource) => void> = {};
		const load = vi.fn((name: string) => new Promise<CanvasImageSource | null>((done) => (later[name] = done)));
		const { l, gl, called } = layer(load);
		const older = l.setIcons([icon(1, "A")]);
		await Promise.resolve(); // its picture is being fetched
		expect(load).toHaveBeenCalledWith("A");
		const newer = l.setIcons([icon(1, "A"), icon(2, "B"), icon(3, "B")]);
		later.A(picture());
		await older;
		l.render(gl, frame);
		expect(called("drawArrays")).toHaveLength(0); // the older set: not drawn
		await vi.waitFor(() => expect(load).toHaveBeenCalledWith("B"));
		later.B(picture());
		await newer;
		l.render(gl, frame);
		expect(called("drawArrays")[0]?.args[2]).toBe(18); // the newer: its 3 icons
	});

	it("emptied: none drawn", async () => {
		const { l, gl, called } = layer();
		await l.setIcons([icon(1, "A")]);
		await l.setIcons([]);
		l.render(gl, frame);
		expect(called("drawArrays")).toHaveLength(0);
	});

	it("a picture that won't load: the icon is still drawn", async () => {
		const { l, gl, called } = layer(vi.fn(async () => null));
		await l.setIcons([icon(1, "Gone")]);
		l.render(gl, frame);
		expect(called("drawArrays")).toHaveLength(1);
	});

	it("a click on an icon: its id, read from the next frame drawn (not before)", async () => {
		const { l, gl, draws } = layer();
		await l.setIcons([icon(1, "Breach"), icon(7, "Breach", 1)]);
		l.render(gl, frame);
		const answer = l.pickAt(1, 1);
		expect(await settled(answer)).toBe(false);
		draws(7 + 1); // icon 7 drawn there (codes are ids + 1)
		l.render(gl, frame);
		await expect(answer).resolves.toBe(7);
	});

	it("answers a click from the next frame drawn", async () => {
		const { l, gl } = layer();
		await expect(l.pickAt(1, 1)).resolves.toBeNull(); // nothing drawn yet
		await l.setIcons([icon(1, "Breach")]);
		l.render(gl, frame);
		const answer = l.pickAt(1, 1);
		l.render(gl, frame);
		await expect(answer).resolves.toBeNull();
		l.onRemove();
	});
});
