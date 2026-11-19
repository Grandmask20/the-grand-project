import { createContext, type ReactNode, useContext, useEffect, useRef } from "react";
import { useAppStore } from "@/store/AppStore";

/** The map layer the settings around shape (none outside a RevealWhileUsed). */
const LayerOfSection = createContext<string | null>(null);

/**
 * A View section whose settings show their layer on the map while you use them, even if its switch is off: while a
 * control in it is held (a slider dragged) or a dropdown of it is open, and a moment after (user: a hidden layer
 * stayed hidden while restyled, then stayed shown until the tab changed; it should show only while you're at it).
 */
export function RevealWhileUsed({ layer, children }: { layer: string; children: ReactNode }) {
	const hold = useAppStore((s) => s.hold);
	return (
		<LayerOfSection.Provider value={layer}>
			<div
				className="contents"
				onPointerDownCapture={() => {
					const release = hold(layer);
					window.addEventListener("pointerup", release, { once: true });
					window.addEventListener("pointercancel", release, { once: true });
				}}
			>
				{children}
			</div>
		</LayerOfSection.Provider>
	);
}

/** A dropdown's open state for the section it is in: open, its layer shows (the list opens outside the section). */
export function useHoldWhileOpen(): (open: boolean) => void {
	const layer = useContext(LayerOfSection);
	const hold = useAppStore((s) => s.hold);
	const release = useRef<(() => void) | null>(null);
	// closed by going away (the tab switched): let go
	useEffect(() => () => release.current?.(), []);
	return (open: boolean) => {
		release.current?.();
		release.current = open && layer ? hold(layer) : null;
	};
}
