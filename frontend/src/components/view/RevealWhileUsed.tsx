import { createContext, type ReactNode, useContext, useEffect, useRef } from "react";
import { VIEW_NOTICE } from "@/hooks/app/UseShownSettings";
import { useAppStore } from "@/store/AppStore";

/** What the settings around hold while used: their layer, or the notice that their view isn't the one shown. */
const HeldBySection = createContext<string | null>(null);

const isPicker = (t: EventTarget) => t instanceof HTMLInputElement && t.type === "color";

/**
 * A View section whose settings show their layer on the map while you use them, even if its switch is off: while a
 * control in it is held (a slider dragged, a colour picker open) or a dropdown of it is open, no longer (user: a
 * hidden layer stayed hidden while restyled, then stayed shown until the tab changed). Settings of the view not shown
 * (`view`: the 3D view's while the map is flat, or the other way round) show a notice over the map instead.
 */
export function RevealWhileUsed({ layer, view, children }: { layer: string; view: "2d" | "3d"; children: ReactNode }) {
	const hold = useAppStore((s) => s.hold);
	const tilted = useAppStore((s) => (s.camera?.pitch ?? 0) > 1);
	const key = (view === "3d") === tilted ? layer : `${VIEW_NOTICE}${view}`;
	const picker = useRef<(() => void) | null>(null);
	const pickerDone = () => {
		picker.current?.();
		picker.current = null;
	};
	// gone with a picker open (the tab switched): let go
	useEffect(
		() => () => {
			picker.current?.();
			picker.current = null;
		},
		[],
	);
	return (
		<HeldBySection.Provider value={key}>
			<div
				className="contents"
				onPointerDownCapture={(e) => {
					if (isPicker(e.target)) return; // (held while its picker is open, below)
					const release = hold(key);
					window.addEventListener("pointerup", release, { once: true });
					window.addEventListener("pointercancel", release, { once: true });
				}}
				// a colour picker: open from its click until it closes (the browser's own "change": React's onChange
				// comes with every colour passed while dragging in it) or loses focus
				onClickCapture={(e) => {
					const t = e.target;
					if (!isPicker(t)) return;
					pickerDone();
					picker.current = hold(key);
					t.addEventListener("change", pickerDone, { once: true });
				}}
				onBlurCapture={pickerDone}
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
