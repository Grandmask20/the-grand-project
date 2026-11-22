import { createContext, type ReactNode, useContext, useEffect, useRef } from "react";
import { VIEW_NOTICE } from "@/hooks/app/UseShownSettings";
import { useAppStore } from "@/store/AppStore";

/** What the settings around hold while used: their layer, or the notice that their view isn't the one shown. */
const HeldBySection = createContext<string | null>(null);

const isPicker = (t: EventTarget) => t instanceof HTMLInputElement && t.type === "color";

/** A section's fold title (Section foldable): opening or folding it uses no setting, so its layer doesn't show. */
const isFold = (t: EventTarget) => t instanceof Element && t.closest("[data-fold]") !== null;

/** Let go of what a ref holds, once. */
function letGo(r: { current: (() => void) | null }) {
	r.current?.();
	r.current = null;
}

/** The keys that change a setting (a box, a slider, a dropdown's choice). */
const CHANGE_KEYS = new Set([
	" ",
	"Enter",
	"ArrowUp",
	"ArrowDown",
	"ArrowLeft",
	"ArrowRight",
	"Home",
	"End",
	"PageUp",
	"PageDown",
]);

/**
 * A View section whose settings show their layer on the map while you use them, even if its switch is off: while a
 * control in it is held (a slider dragged, a colour picker open) or a dropdown of it is open, no longer (user: a
 * hidden layer stayed hidden while restyled, then stayed shown until the tab changed). Settings of the view not shown
 * (`view`: the 3D view's while the map is flat, or the other way round) show a notice over the map instead.
 */
export function RevealWhileUsed({ layer, view, children }: { layer: string; view: "2d" | "3d"; children: ReactNode }) {
	const hold = useAppStore((s) => s.hold);
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const held = (view === "3d") === tilted ? layer : `${VIEW_NOTICE}${view}`;
	// what is held now, each let go once: a press (until the mouse is let go anywhere), a key (until it is let go or
	// the control is left), a colour picker (until it closes or is left)
	const press = useRef<(() => void) | null>(null);
	const key = useRef<(() => void) | null>(null);
	const picker = useRef<(() => void) | null>(null);
	const pickerDone = () => letGo(picker);
	// gone while held (the tab switched): let go
	useEffect(
		() => () => {
			for (const r of [press, key, picker]) letGo(r);
		},
		[],
	);
	return (
		<HeldBySection.Provider value={held}>
			<div
				className="contents"
				onPointerDownCapture={(e) => {
					if (isPicker(e.target) || isFold(e.target)) return; // (a picker: held while open, below)
					letGo(press);
					const release = hold(held);
					// one end for both ways a press ends, which takes both listeners off (one stayed: CodeRabbit)
					const end = () => {
						window.removeEventListener("pointerup", end);
						window.removeEventListener("pointercancel", end);
						release();
						if (press.current === end) press.current = null;
					};
					press.current = end;
					window.addEventListener("pointerup", end);
					window.addEventListener("pointercancel", end);
				}}
				// the keyboard too (Space on a box, arrows on a slider: CodeRabbit)
				onKeyDownCapture={(e) => {
					if (CHANGE_KEYS.has(e.key) && !key.current && !isFold(e.target)) key.current = hold(held);
				}}
				onKeyUpCapture={() => letGo(key)}
				// a colour picker: open from its click until it closes (the browser's own "change": React's onChange
				// comes with every colour passed while dragging in it) or loses focus
				onClickCapture={(e) => {
					const t = e.target;
					if (!isPicker(t)) return;
					pickerDone();
					picker.current = hold(held);
					t.addEventListener("change", pickerDone, { once: true });
				}}
				onBlurCapture={() => {
					letGo(key);
					pickerDone();
				}}
			>
				{children}
			</div>
		</HeldBySection.Provider>
	);
}

/** A dropdown's open state for the section it is in: open, its layer shows (the list opens outside the section). */
export function useHoldWhileOpen(): (open: boolean) => void {
	const layer = useContext(HeldBySection);
	const hold = useAppStore((s) => s.hold);
	const release = useRef<(() => void) | null>(null);
	// closed by going away (the tab switched): let go
	useEffect(() => () => release.current?.(), []);
	return (open: boolean) => {
		release.current?.();
		release.current = open && layer ? hold(layer) : null;
	};
}
