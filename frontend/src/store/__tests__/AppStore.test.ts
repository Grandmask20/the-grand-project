import { describe, expect, it } from "vitest";
import { useAppStore } from "@/store/AppStore";

describe("useAppStore", () => {
	it("counts fly and fit requests so the same spot can be asked twice", () => {
		const s = useAppStore.getState();
		s.flyTo(1, 2);
		s.flyTo(1, 2);
		expect(useAppStore.getState().fly).toEqual({ x: 1, y: 2, px: undefined, n: 2 });
		s.requestFit();
		expect(useAppStore.getState().fitAtlas).toBe(1);
	});

	it("patches the replay only while one is open", () => {
		const s = useAppStore.getState();
		s.patchReplay({ pos: 3 });
		expect(useAppStore.getState().replay).toBeNull();
	});

	it("shows an error's message", () => {
		useAppStore.getState().showError(new Error("boom"));
		expect(useAppStore.getState().error).toBe("boom");
		useAppStore.getState().showError(null);
		expect(useAppStore.getState().error).toBeNull();
	});
});
