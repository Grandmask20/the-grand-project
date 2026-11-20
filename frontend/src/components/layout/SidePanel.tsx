import { XIcon } from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { AutoAddTab } from "@/components/adding/AutoAddTab";
import { AtlasesTab } from "@/components/atlases/AtlasesTab";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { FindTab } from "@/components/find/FindTab";
import { PagedTab } from "@/components/layout/PagedTab";
import { RouteTab } from "@/components/route/RouteTab";
import { ViewTab } from "@/components/view/ViewTab";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { SIDE_TABS, SideRail } from "./SideRail";

/** The drawer's width range in px (dragging its edge; user: resize the panel, not zoom it). */
const SIDE_MIN = 300;
const SIDE_MAX = 720;
const SIDE_DEFAULT = 400;

/**
 * The side panel: the rail of its tabs, and the drawer of the tab open (PO's layout A: the rail's tab clicked again
 * folds the drawer away for more map). The layers are in the status line, the log under the map.
 */
export function SidePanel() {
	const tab = useAppStore((s) => s.tab);
	const open = useAppStore((s) => s.panelOpen);
	const setOpen = useAppStore((s) => s.setPanelOpen);
	const page = useAppStore((s) => s.pages[s.tab] ?? "");
	const gen = useAppState().data?.generation ?? 0;
	const settings = useSettings();
	const update = useUpdateSettings();
	const side = settings?.ui.side ?? "left";
	const saved = settings?.ui.side_width ?? SIDE_DEFAULT;
	const [width, setWidth] = useState(saved);
	const drag = useRef<{ x: number; w: number } | null>(null);
	const title = SIDE_TABS.find(([k]) => k === tab)?.[1] ?? "";

	useEffect(() => setWidth(saved), [saved]);

	// another page of the tab: back at the top (the tab's own scroll box stays: the picker keeps the focus)
	const scroller = useRef<HTMLDivElement>(null);
	useEffect(() => {
		if (page !== undefined) scroller.current?.scrollTo({ top: 0 });
	}, [page]);

	const onDown = (e: ReactPointerEvent) => {
		drag.current = { x: e.clientX, w: width };
		(e.target as HTMLElement).setPointerCapture(e.pointerId);
	};
	const onMove = (e: ReactPointerEvent) => {
		if (!drag.current) return;
		const dx = (e.clientX - drag.current.x) * (side === "left" ? 1 : -1);
		setWidth(Math.min(SIDE_MAX, Math.max(SIDE_MIN, drag.current.w + dx)));
	};
	const onUp = () => {
		if (!drag.current) return;
		drag.current = null;
		update.mutate({ ui: { side_width: Math.round(width) } });
	};

	return (
		<div className={cn("flex h-full shrink-0", side === "right" && "flex-row-reverse")}>
			<SideRail side={side} />
			{open && (
				<aside
					className={cn("relative flex h-full flex-col bg-background", side === "left" ? "border-r" : "border-l")}
					style={{ width }}
				>
					<div className="flex items-center justify-between px-3 pt-3 pb-1">
						<h2 className="text-base font-semibold">{title}</h2>
						<button
							type="button"
							aria-label="Close the panel"
							title="Close the panel (its tab on the rail opens it again)"
							onClick={() => {
								// the focus goes to the tab on the rail, not lost with the button (CodeRabbit)
								document.getElementById(`side-tab-${tab}`)?.focus();
								setOpen(false);
							}}
							className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
						>
							<XIcon className="size-4" />
						</button>
					</div>
					{/* keyed by the tab, so a tab opens at its top, not at the scroll of the one before; and by the atlas,
					    so what a tab picked (bookmarks, a waiting group) doesn't carry over to another atlas. Another page
					    of the same tab only scrolls back up (keyed by the page too, its picker lost the focus: CodeRabbit) */}
					<div
						ref={scroller}
						key={`${tab}|${gen}`}
						id="side-panel"
						role="tabpanel"
						aria-labelledby={`side-tab-${tab}`}
						className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-3"
					>
						{tab === "find" && <FindTab />}
						{tab === "view" && <ViewTab />}
						{tab === "bookmarks" && (
							<PagedTab
								tab="bookmarks"
								label="Saved pages"
								pages={[
									["bookmarks", "Bookmarks", <BookmarksTab key="b" />],
									["route", "Route", <RouteTab key="r" />],
								]}
							/>
						)}
						{tab === "atlases" && (
							<PagedTab
								tab="atlases"
								label="Atlases pages"
								pages={[
									["atlases", "Saved atlases", <AtlasesTab key="a" />],
									["auto", "Auto-add", <AutoAddTab key="w" />],
								]}
							/>
						)}
					</div>
					<div
						aria-hidden="true"
						title="Drag to resize the side panel (double-click: back to normal)"
						onPointerDown={onDown}
						onPointerMove={onMove}
						onPointerUp={onUp}
						onDoubleClick={() => update.mutate({ ui: { side_width: SIDE_DEFAULT } })}
						className={cn(
							"absolute top-0 z-20 h-full w-1.5 cursor-col-resize hover:bg-gold/40",
							side === "left" ? "-right-1" : "-left-1",
						)}
					/>
				</aside>
			)}
		</div>
	);
}
