import { useAppState } from "@/hooks/app/UseAppState";
import { useCursorAt } from "@/hooks/map/UseCursorAt";
import { useAppStore } from "@/store/AppStore";

/** The status line, the mode's hint, and where the mouse is on the atlas. */
export function StatusBar({ connected }: { connected: boolean }) {
	const state = useAppState().data;
	const mode = useAppStore((s) => s.mode);

	const hint =
		mode.kind === "lasso"
			? "draw around the maps of the biome (hold the left button); Esc cancels"
			: mode.kind === "bookmark"
				? "click where the bookmark goes; Esc cancels"
				: mode.kind === "player"
					? "click the map you are on; Esc cancels"
					: mode.kind === "ghost"
						? "drag the screenshot roughly where it belongs, then Enter or double-click; Esc cancels"
						: mode.kind === "debug-link"
							? "debug: now click the map this one should have a path to"
							: "";

	return (
		<footer className="flex h-7 shrink-0 items-center gap-4 border-t bg-card px-3 font-mono text-xs text-muted-foreground">
			{!connected && <span className="text-destructive">not connected to the app</span>}
			<span className="truncate text-foreground">{hint || state?.status}</span>
			<span className="flex-1" />
			{state?.busy && <span className="text-gold">working…</span>}
			<CursorAt />
		</footer>
	);
}

/** The mouse's place on the atlas (redrawn alone on every mouse move). */
function CursorAt() {
	return <span>{useCursorAt()}</span>;
}
