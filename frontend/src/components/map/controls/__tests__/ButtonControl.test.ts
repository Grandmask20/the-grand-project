import { describe, expect, it, vi } from "vitest";
import { ButtonControl } from "@/components/map/controls/ButtonControl";

describe("ButtonControl", () => {
	it("is one button in MapLibre's control look, named for screen readers, lit when on", () => {
		const click = vi.fn();
		const c = new ButtonControl("3D", "3D view", click);
		const el = c.onAdd();
		expect(el.className).toBe("maplibregl-ctrl maplibregl-ctrl-group");
		const b = el.querySelector("button") as HTMLButtonElement;
		expect([b.textContent, b.title, b.getAttribute("aria-label")]).toEqual(["3D", "3D view", "3D view"]);
		b.click();
		expect(click).toHaveBeenCalledOnce();
		c.setOn(true);
		expect(b.classList.contains("on")).toBe(true);
	});

	it("clicks do what was set last, and it goes with the map", () => {
		const first = vi.fn();
		const later = vi.fn();
		const c = new ButtonControl("⤢", "Fit", first);
		const parent = document.createElement("div");
		parent.appendChild(c.onAdd());
		c.setOnClick(later);
		parent.querySelector("button")?.click();
		expect([first.mock.calls.length, later.mock.calls.length]).toEqual([0, 1]);
		c.onRemove();
		expect(parent.children).toHaveLength(0);
	});
});
