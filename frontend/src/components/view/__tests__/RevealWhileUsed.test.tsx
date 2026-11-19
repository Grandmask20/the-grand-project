import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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

	it("the other view's settings show a notice, not their layer (3D settings on the flat map)", () => {
		render(
			<RevealWhileUsed layer="Paths" view="3d">
				<button type="button">slider</button>
			</RevealWhileUsed>,
		);
		fireEvent.pointerDown(screen.getByRole("button", { name: "slider" }));
		expect(useAppStore.getState().editing).toEqual(["view:3d"]);
		fireEvent.pointerUp(window);
		act(() => useAppStore.getState().setCamera({ pitch: 40 } as never)); // tilted: now they show
		fireEvent.pointerDown(screen.getByRole("button", { name: "slider" }));
		expect(useAppStore.getState().editing).toEqual(["Paths"]);
	});
});
