import { ChevronDownIcon, ChevronUpIcon, TerminalIcon } from "lucide-react";
import { LayersPopover } from "@/components/view/LayersPopover";
import { useAppState } from "@/hooks/app/UseAppState";
import { useCursorAt } from "@/hooks/map/UseCursorAt";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { MapButtons } from "./MapButtons";

const Divider = () => <span className="h-4 w-px shrink-0 bg-border" aria-hidden />;

/**
 * The status line: the app's status, the atlas's numbers and where the mouse is on it, then the map's camera, its
 * layers and the log (PO: nothing over the map but what needs it; the mode's hint is the line above the map).
 */
export function StatusBar({ connected }: { connected: boolean }) {
	const state = useAppState().data;
	const logOpen = useAppStore((s) => s.logOpen);
	const setLogOpen = useAppStore((s) => s.setLogOpen);
	const atlas = state?.atlas;

	return (
		<footer className="flex h-8 shrink-0 items-center gap-3 border-t bg-card px-3 font-mono text-xs text-muted-foreground">
			{!connected && <span className="text-destructive">not connected to the app</span>}
			<span className="min-w-0 truncate text-foreground">{state?.status}</span>
			<span className="flex-1" />
			{state?.busy && <span className="text-gold">working…</span>}
			{atlas && (
				<span className="truncate" title={atlas.path}>
					{atlas.maps} maps · {atlas.icons} icons · {atlas.landmarks} landmarks · {atlas.shots} screenshots
				</span>
			)}
			<CursorAt />
			<Divider />
			<MapButtons />
			<Divider />
			<LayersPopover />
			<button
				type="button"
				aria-expanded={logOpen}
				aria-label="Log"
				title="The log (and Debug in debug mode)"
				onClick={() => setLogOpen(!logOpen)}
				className={cn(
					"flex h-6 items-center gap-1.5 rounded px-2",
					logOpen ? "bg-accent text-foreground" : "hover:bg-accent hover:text-foreground",
				)}
			>
				<TerminalIcon className="size-3.5" aria-hidden />
				Log
				{logOpen ? <ChevronDownIcon className="size-3.5" /> : <ChevronUpIcon className="size-3.5" />}
			</button>
		</footer>
	);
}

/** The mouse's place on the atlas (redrawn alone on every mouse move). */
function CursorAt() {
	return <span className="shrink-0">{useCursorAt()}</span>;
}
