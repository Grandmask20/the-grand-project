import { XIcon } from "lucide-react";
import { ErrorBanner } from "@/components/common/ErrorBanner";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { VIEW_NOTICE } from "@/hooks/app/UseShownSettings";
import { modeHint } from "@/logic/ModeHint";
import { layerOn } from "@/logic/map/AtlasLayers";
import { useAppStore } from "@/store/AppStore";

/** What the other view's settings say while used (View tab, RevealWhileUsed): they don't show in the view on screen. */
const VIEW_NOTES: Record<string, string> = {
	"3d": "These are the 3D view's settings: the map is flat now, so they don't show. Press 3D (right of the map) to tilt it.",
	"2d": "These are the flat map's settings: the 3D view draws its own paths, icons and models, so most of them don't show here (the path colours and the icon style do). Press 3D to see the map flat.",
};

/**
 * The notes over the map, one column at its top so they never cover each other (user: an error covered the Adjust
 * route note): what a click does now in a map mode, with End (user: only Esc ended one), the other view's settings in
 * use, that bookmarks are hidden while their tab is open, and the last error.
 */
export function MapNotes() {
	const mode = useAppStore((s) => s.mode);
	const setMode = useAppStore((s) => s.setMode);
	const asking = useAppStore((s) => s.lassoAsked); // (Biome select's menu is up: the note would say to draw)
	const tab = useAppStore((s) => s.tab);
	const view = useAppStore((s) => s.editing.find((k) => k.startsWith(VIEW_NOTICE))?.slice(VIEW_NOTICE.length));
	const settings = useSettings();
	const update = useUpdateSettings();
	return (
		<div className="pointer-events-none absolute top-2 left-1/2 z-30 flex w-max max-w-[80%] -translate-x-1/2 flex-col items-center gap-1.5">
			{mode.kind !== "normal" && !asking && (
				<div className="pointer-events-auto flex items-center gap-3 rounded-md border border-gold/60 bg-card/95 px-3 py-1.5 text-sm text-gold shadow">
					<span>{modeHint(mode)}</span>
					<button
						type="button"
						className="flex shrink-0 items-center gap-1 rounded border border-gold/60 px-1.5 py-0.5 text-xs hover:bg-accent"
						onClick={() => setMode({ kind: "normal" })}
					>
						<XIcon className="size-3.5" />
						End
					</button>
				</div>
			)}
			{view && VIEW_NOTES[view] && (
				<div role="status" className="max-w-xl rounded-md border border-gold bg-card px-4 py-3 text-base shadow-lg">
					{VIEW_NOTES[view]}
				</div>
			)}
			{tab === "bookmarks" && settings && !layerOn(settings, "Bookmarks") && (
				<div
					role="status"
					className="pointer-events-auto flex items-center gap-3 rounded-md border bg-card/95 px-3 py-1.5 text-sm shadow"
				>
					Bookmarks are currently hidden
					<button
						type="button"
						className="text-gold hover:underline"
						onClick={() => update.mutate({ layers: { Bookmarks: true } })}
					>
						Show them
					</button>
				</div>
			)}
			<ErrorBanner />
		</div>
	);
}
