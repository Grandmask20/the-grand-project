import { XIcon } from "lucide-react";
import { ErrorBanner } from "@/components/common/ErrorBanner";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { modeHint } from "@/logic/ModeHint";
import { layerOn } from "@/logic/map/AtlasLayers";
import { useAppStore } from "@/store/AppStore";

/**
 * The line above the map (PO: nothing on the map but what needs it, the replay and the route): what a click does now
 * in a map mode, with End (user: only Esc ended one), that bookmarks are hidden while the Saved tab is open, and the
 * last error. Nothing to say: no line, the map keeps its height.
 */
export function ModeBar() {
	const mode = useAppStore((s) => s.mode);
	const setMode = useAppStore((s) => s.setMode);
	const asking = useAppStore((s) => s.lassoAsked); // (Biome select's menu is up: the line would say to draw)
	const savedOpen = useAppStore((s) => s.panelOpen && s.tab === "bookmarks");
	const error = useAppStore((s) => !!s.error);
	const settings = useSettings();
	const update = useUpdateSettings();
	const hint = mode.kind !== "normal" && !asking ? modeHint(mode) : "";
	const hidden = savedOpen && !!settings && !layerOn(settings, "Bookmarks");
	if (!hint && !hidden && !error) return null;
	return (
		<div className="flex shrink-0 flex-col gap-1 border-b border-gold/40 bg-card px-3 py-1.5 text-sm">
			{hint && (
				<div className="flex items-center gap-3 text-gold">
					<span className="flex-1">{hint}</span>
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
			{hidden && (
				<div role="status" className="flex items-center gap-3">
					<span className="flex-1">Bookmarks are currently hidden</span>
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
