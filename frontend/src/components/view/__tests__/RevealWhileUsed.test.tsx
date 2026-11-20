import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RevealWhileUsed, useHoldWhileOpen } from "@/components/view/RevealWhileUsed";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

function Dropdown() {
	const holdOpen = useHoldWhileOpen();
	return (
		<>
			<button type="button" onClick={() => holdOpen(true)}>
				open
			</button>
			<button type="button" onClick={() => holdOpen(false)}>
				close
			</button>
		</>
	);
}

describe("RevealWhileUsed", () => {
	afterEach(resetStore);

	it("shows its layer while a control in it is pressed, not after it's let go", () => {
		render(
			<RevealWhileUsed layer="Paths" view="2d">
				<button type="button">slider</button>
			</RevealWhileUsed>,
		);
		fireEvent.pointerDown(screen.getByRole("button", { name: "slider" }));
		expect(useAppStore.getState().editing).toEqual(["Paths"]);
		fireEvent.pointerUp(window);
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("nothing while the replay is open: its settings are locked (CodeRabbit: a heading's press showed the layer)", () => {
		useAppStore.setState({ replay: {} as never });
		render(
			<RevealWhileUsed layer="Paths" view="2d">
				<button type="button">heading</button>
			</RevealWhileUsed>,
		);
		fireEvent.pointerDown(screen.getByRole("button", { name: "heading" }));
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("shows its layer while a dropdown in it is open (the list is outside the section)", () => {
		render(
			<RevealWhileUsed layer="Icons" view="2d">
				<Dropdown />
			</RevealWhileUsed>,
		);
		fireEvent.click(screen.getByRole("button", { name: "open" }));
		fireEvent.pointerUp(window); // (the click's own press, let go)
		expect(useAppStore.getState().editing).toEqual(["Icons"]);
		fireEvent.click(screen.getByRole("button", { name: "close" }));
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("a colour picker: shown from its click until it closes", () => {
		render(
			<RevealWhileUsed layer="Paths" view="2d">
				<input type="color" aria-label="colour" />
			</RevealWhileUsed>,
		);
		const picker = screen.getByLabelText("colour");
		fireEvent.click(picker);
		fireEvent.input(picker, { target: { value: "#ff0000" } }); // (dragging in it: still open)
		expect(useAppStore.getState().editing).toEqual(["Paths"]);
		picker.dispatchEvent(new Event("change", { bubbles: true }));
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("the other view's settings show nothing, not their layer (3D settings on the flat map)", () => {
		render(
			<RevealWhileUsed layer="Paths" view="3d">
				<button type="button">slider</button>
			</RevealWhileUsed>,
		);
		fireEvent.pointerDown(screen.getByRole("button", { name: "slider" }));
		expect(useAppStore.getState().editing).toEqual([]);
		fireEvent.pointerUp(window);
		act(() => useAppStore.getState().setCamera({ pitch: 40 } as never)); // tilted: now they show
		fireEvent.pointerDown(screen.getByRole("button", { name: "slider" }));
		expect(useAppStore.getState().editing).toEqual(["Paths"]);
	});

	it("the keyboard holds too, from key down to key up (CodeRabbit)", () => {
		render(
			<RevealWhileUsed layer="3D models" view="2d">
				<input type="checkbox" aria-label="beams" />
			</RevealWhileUsed>,
		);
		const box = screen.getByLabelText("beams");
		fireEvent.keyDown(box, { key: " " });
		expect(useAppStore.getState().editing).toEqual(["3D models"]);
		fireEvent.keyUp(box, { key: " " });
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("a press ends once, both window listeners taken off (one stayed and they piled up: CodeRabbit)", () => {
		const added = vi.spyOn(window, "addEventListener");
		const removed = vi.spyOn(window, "removeEventListener");
		render(
			<RevealWhileUsed layer="Paths" view="2d">
				<button type="button">slider</button>
			</RevealWhileUsed>,
		);
		fireEvent.pointerDown(screen.getByRole("button", { name: "slider" }));
		fireEvent.pointerUp(window);
		const mine = (spy: typeof added) =>
			spy.mock.calls.filter(([t]) => t === "pointerup" || t === "pointercancel").length;
		expect(mine(added)).toBe(2);
		expect(mine(removed)).toBe(2);
		added.mockRestore();
		removed.mockRestore();
	});
});
