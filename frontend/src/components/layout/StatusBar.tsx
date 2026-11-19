import { useAppState } from "@/hooks/app/UseAppState";
import { useCursorAt } from "@/hooks/map/UseCursorAt";
import { modeHint } from "@/logic/ModeHint";
import { useAppStore } from "@/store/AppStore";

/** The status line, the mode's hint, and where the mouse is on the atlas. */
export function StatusBar({ connected }: { connected: boolean }) {
	const state = useAppState().data;
	const mode = useAppStore((s) => s.mode);

	const hint = modeHint(mode);

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
