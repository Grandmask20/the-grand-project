import { ChevronDownIcon } from "lucide-react";
import { useId } from "react";
import { PagePicker, pageIds } from "@/components/common/PagePicker";
import { DebugTab } from "@/components/debug/DebugTab";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";
import { LogTab } from "./LogTab";

/**
 * The log under the map, opened from the status line (it was the side panel's Log tab: PO, the first UI draft), with
 * the Debug page in debug mode. Closed, it takes no room.
 */
export function LogDrawer() {
	const open = useAppStore((s) => s.logOpen);
	const asked = useAppStore((s) => s.logPage);
	const setOpen = useAppStore((s) => s.setLogOpen);
	const setPage = useAppStore((s) => s.setLogPage);
	const debug = !!useAppState().data?.debug;
	const idBase = useId();
	if (!open) return null;
	const pages: ["log" | "debug", string][] = debug
		? [
				["log", "Log"],
				["debug", "Debug"],
			]
		: [["log", "Log"]];
	const page = debug && asked === "debug" ? "debug" : "log";
	const ids = pageIds(idBase, page);
	return (
		<section aria-label="Log" className="flex h-60 shrink-0 flex-col border-t bg-background">
			<div className="flex items-center gap-2 border-b px-3 pt-2">
				<PagePicker
					label="Log pages"
					pages={pages}
					value={page}
					onChange={setPage}
					idBase={idBase}
					className="border-b-0"
				/>
				<span className="flex-1" />
				<button
					type="button"
					aria-label="Close the log"
					title="Close the log"
					onClick={() => setOpen(false)}
					className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
				>
					<ChevronDownIcon className="size-4" />
				</button>
			</div>
			<div
				id={ids.panel}
				role="tabpanel"
				aria-labelledby={ids.tab}
				className="min-h-0 flex-1 overflow-y-auto px-3 py-2"
			>
				{page === "debug" ? <DebugTab /> : <LogTab />}
			</div>
		</section>
	);
}
