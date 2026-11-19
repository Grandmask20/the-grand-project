import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RevealWhileUsed, useHoldWhileOpen } from "@/components/view/RevealWhileUsed";
import { REVEAL_LINGER_MS, useAppStore } from "@/store/AppStore";
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
	afterEach(() => {
		vi.useRealTimers();
		resetStore();
	});

	it("shows its layer while a control in it is pressed, and a moment after it's let go", () => {
		vi.useFakeTimers();
		render(
			<RevealWhileUsed layer="Paths">
				<button type="button">slider</button>
			</RevealWhileUsed>,
		);
		fireEvent.pointerDown(screen.getByRole("button", { name: "slider" }));
		expect(useAppStore.getState().editing).toEqual(["Paths"]);
		act(() => vi.advanceTimersByTime(REVEAL_LINGER_MS * 3)); // (still held: dragging)
		expect(useAppStore.getState().editing).toEqual(["Paths"]);
		fireEvent.pointerUp(window);
		act(() => vi.advanceTimersByTime(REVEAL_LINGER_MS + 10));
		expect(useAppStore.getState().editing).toEqual([]);
	});

	it("shows its layer while a dropdown in it is open (the list is outside the section)", () => {
		vi.useFakeTimers();
		render(
			<RevealWhileUsed layer="Icons">
				<Dropdown />
			</RevealWhileUsed>,
		);
		fireEvent.click(screen.getByRole("button", { name: "open" }));
		fireEvent.pointerUp(window); // (the click's own press, let go)
		act(() => vi.advanceTimersByTime(REVEAL_LINGER_MS * 3));
		expect(useAppStore.getState().editing).toEqual(["Icons"]);
		fireEvent.click(screen.getByRole("button", { name: "close" }));
		act(() => vi.advanceTimersByTime(REVEAL_LINGER_MS + 10));
		expect(useAppStore.getState().editing).toEqual([]);
	});
});
