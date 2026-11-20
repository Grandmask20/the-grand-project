import {
	BookmarkIcon,
	FolderOpenIcon,
	type LucideIcon,
	ScrollTextIcon,
	SearchIcon,
	SlidersHorizontalIcon,
} from "lucide-react";
import { type ReactNode, type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { AutoAddTab } from "@/components/adding/AutoAddTab";
import { AtlasesTab } from "@/components/atlases/AtlasesTab";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { DebugTab } from "@/components/debug/DebugTab";
import { FindTab } from "@/components/find/FindTab";
import { PagedTab } from "@/components/layout/PagedTab";
import { LogTab } from "@/components/log/LogTab";
import { RouteTab } from "@/components/route/RouteTab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LayersDock } from "@/components/view/LayersDock";
import { ViewTab } from "@/components/view/ViewTab";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

// five tabs with icons (user, from banner's mock: "find view and bookmark are 100% things i want"); Auto-add is a
// page of Atlases, Route of Bookmarks, and Debug of Log (PAGE_OF in the store)
const TABS: [string, string, LucideIcon][] = [
	["find", "Find", SearchIcon],
	["view", "View", SlidersHorizontalIcon],
	["bookmarks", "Bookmarks", BookmarkIcon],
	["atlases", "Atlases", FolderOpenIcon],
	["log", "Log", ScrollTextIcon],
];

/** The side panel's width range in px (dragging its edge; user: resize the panel, not zoom it). */
const SIDE_MIN = 300;
const SIDE_MAX = 720;
const SIDE_DEFAULT = 400;

/** The side panel: its tabs, and the layers ("Show on the map") always at its bottom, as in the old window. */
export function SidePanel({ debug }: { debug: boolean }) {
	const tab = useAppStore((s) => s.tab);
	const page = useAppStore((s) => s.pages[s.tab] ?? "");
	const setTab = useAppStore((s) => s.setTab);
	const gen = useAppState().data?.generation ?? 0;
	const settings = useSettings();
	const update = useUpdateSettings();
	const side = settings?.ui.side ?? "left";
	const saved = settings?.ui.side_width ?? SIDE_DEFAULT;
	const [width, setWidth] = useState(saved);
	const drag = useRef<{ x: number; w: number } | null>(null);

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
		<aside
			className={cn("relative flex h-full shrink-0 flex-col bg-background", side === "left" ? "border-r" : "border-l")}
			style={{ width }}
		>
			<Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
				{/* one row that scrolls sideways when the panel is narrow (it wrapped onto the panel before) */}
				<TabsList className="@container m-2 mb-0 flex h-auto w-auto shrink-0 flex-nowrap justify-start overflow-x-auto pb-2.5 [scrollbar-width:thin]">
					{/* the tabs share the row's width, with their names or without: the names go only when the row itself is
					    too narrow for them (a container query, ~23.5rem), so narrowing the panel doesn't make the icons jump
					    or bunch up at the left (user: "a bit too jumpy") */}
					{TABS.map(([k, label, Icon]) => (
						<TabsTrigger key={k} value={k} className="min-w-0 flex-auto gap-1 px-2" title={label} aria-label={label}>
							<Icon className="size-4 shrink-0" aria-hidden="true" />
							<span className="hidden @min-[23.5rem]:inline">{label}</span>
						</TabsTrigger>
					))}
				</TabsList>
				{/* keyed by the tab, so a tab opens at its top, not at the scroll of the one before; and by the atlas, so
				    what a tab picked (bookmarks, a waiting group) doesn't carry over to another atlas. Another page of the
				    same tab only scrolls back up (keyed by the page too, its picker lost the focus: CodeRabbit) */}
				<div ref={scroller} key={`${tab}|${gen}`} className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-3">
					<TabsContent value="find" className="h-full">
						<FindTab />
					</TabsContent>
					<TabsContent value="bookmarks">
						<PagedTab
							tab="bookmarks"
							label="Bookmarks pages"
							pages={[
								["bookmarks", "Bookmarks", <BookmarksTab key="b" />],
								["route", "Route", <RouteTab key="r" />],
							]}
						/>
					</TabsContent>
					<TabsContent value="atlases">
						<PagedTab
							tab="atlases"
							label="Atlases pages"
							pages={[
								["atlases", "Saved atlases", <AtlasesTab key="a" />],
								["auto", "Auto-add", <AutoAddTab key="w" />],
							]}
						/>
					</TabsContent>
					<TabsContent value="view">
						<ViewTab />
					</TabsContent>
					<TabsContent value="log" className="h-full">
						<PagedTab
							tab="log"
							label="Log pages"
							pages={[
								["log", "Log", <LogTab key="l" />],
								...(debug ? [["debug", "Debug", <DebugTab key="d" />] as [string, string, ReactNode]] : []),
							]}
						/>
					</TabsContent>
				</div>
			</Tabs>
			<LayersDock />
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
	);
}
