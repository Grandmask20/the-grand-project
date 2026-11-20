import { BookmarkIcon, FolderOpenIcon, type LucideIcon, SearchIcon, SlidersHorizontalIcon } from "lucide-react";
import { type KeyboardEvent, useRef } from "react";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** The side panel's tabs: id, name, icon, what it holds. "Saved" is the bookmarks tab (bookmarks, saved routes, where
 * you are): PO, a better name than "Bookmarks" for both. The log is under the map now (LogDrawer). */
export const SIDE_TABS: [string, string, LucideIcon, string][] = [
	["find", "Find", SearchIcon, "Find: search, and the types the map shows"],
	["view", "View", SlidersHorizontalIcon, "View settings"],
	["bookmarks", "Saved", BookmarkIcon, "Saved: bookmarks, routes, where you are"],
	["atlases", "Atlases", FolderOpenIcon, "Atlases and Auto-add"],
];

/**
 * The rail of the side panel's tabs (PO's layout A): a tab opens the drawer on it; the tab open, clicked again, folds
 * the drawer away for more map. Tabs as the WAI pattern has them: one stop for Tab, the arrow keys move and open.
 */
export function SideRail({ side }: { side: "left" | "right" }) {
	const tab = useAppStore((s) => s.tab);
	const open = useAppStore((s) => s.panelOpen);
	const setTab = useAppStore((s) => s.setTab);
	const setOpen = useAppStore((s) => s.setPanelOpen);
	const buttons = useRef(new Map<string, HTMLButtonElement>());

	const pick = (k: string) => (k === tab && open ? setOpen(false) : setTab(k));
	const keys = (e: KeyboardEvent<HTMLDivElement>) => {
		const at = SIDE_TABS.findIndex(([k]) => k === tab);
		const to = { ArrowDown: at + 1, ArrowUp: at - 1, Home: 0, End: SIDE_TABS.length - 1 }[e.key];
		if (to === undefined) return;
		e.preventDefault();
		const [k] = SIDE_TABS[(to + SIDE_TABS.length) % SIDE_TABS.length];
		setTab(k);
		buttons.current.get(k)?.focus();
	};

	return (
		<div
			role="tablist"
			aria-label="Side panel"
			aria-orientation="vertical"
			onKeyDown={keys}
			className={cn(
				"flex w-16 shrink-0 flex-col items-center gap-1 bg-card py-2",
				side === "left" ? "border-r" : "border-l",
			)}
		>
			{SIDE_TABS.map(([k, label, Icon, title]) => {
				const on = k === tab && open;
				return (
					<button
						key={k}
						ref={(b) => {
							if (b) buttons.current.set(k, b);
							else buttons.current.delete(k);
						}}
						id={`side-tab-${k}`}
						type="button"
						role="tab"
						aria-selected={on}
						aria-controls={on ? "side-panel" : undefined}
						tabIndex={k === tab ? 0 : -1}
						title={title}
						onClick={() => pick(k)}
						className={cn(
							"flex h-14 w-14 flex-col items-center justify-center gap-1 rounded-md text-[11px] font-medium",
							on ? "bg-accent text-gold" : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
						)}
					>
						<Icon className="size-5" aria-hidden />
						{label}
					</button>
				);
			})}
		</div>
	);
}
