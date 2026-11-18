import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from "react";
import { AutoAddTab } from "@/components/adding/AutoAddTab";
import { AtlasesTab } from "@/components/atlases/AtlasesTab";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { DebugTab } from "@/components/debug/DebugTab";
import { FindTab } from "@/components/find/FindTab";
import { LogTab } from "@/components/log/LogTab";
import { RouteTab } from "@/components/route/RouteTab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { LayersDock } from "@/components/view/LayersDock";
import { ViewTab } from "@/components/view/ViewTab";
import { useAppState } from "@/hooks/app/UseAppState";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

// the old window's order (user), with Route (new) after the atlases; Debug and then Log at the end
const TABS: [string, string][] = [
	["find", "Find"],
	["view", "View"],
	["auto", "Auto-add"],
	["bookmarks", "Bookmarks"],
	["atlases", "Saved atlases"],
	["route", "Route"],
];

/** The side panel's width range in px (dragging its edge; user: resize the panel, not zoom it). */
const SIDE_MIN = 300;
const SIDE_MAX = 720;
const SIDE_DEFAULT = 400;

/** The side panel: its tabs, and the layers ("Show on the map") always at its bottom, as in the old window. */
export function SidePanel({ debug }: { debug: boolean }) {
	const tab = useAppStore((s) => s.tab);
	const setTab = useAppStore((s) => s.setTab);
	const gen = useAppState().data?.generation ?? 0;
	const settings = useSettings();
	const update = useUpdateSettings();
	const side = settings?.ui.side ?? "left";
	const saved = settings?.ui.side_width ?? SIDE_DEFAULT;
	const [width, setWidth] = useState(saved);
	const drag = useRef<{ x: number; w: number } | null>(null);
	const tabs: [string, string][] = [
		...TABS,
		...(debug ? [["debug", "Debug"] as [string, string]] : []),
		["log", "Log"],
	];

	useEffect(() => setWidth(saved), [saved]);

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
				<TabsList className="m-2 mb-0 flex h-auto w-auto shrink-0 flex-nowrap justify-start overflow-x-auto pb-2.5 [scrollbar-width:thin]">
					{tabs.map(([k, label]) => (
						<TabsTrigger key={k} value={k} className="shrink-0 grow-0 px-2.5">
							{label}
						</TabsTrigger>
					))}
				</TabsList>
				{/* keyed by the tab, so a tab opens at its top, not at the scroll of the one before; and by the atlas, so
				    what a tab picked (bookmarks, a waiting group) doesn't carry over to another atlas */}
				<div key={`${tab}|${gen}`} className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto p-3">
					<TabsContent value="find" className="h-full">
						<FindTab />
					</TabsContent>
					<TabsContent value="bookmarks">
						<BookmarksTab />
					</TabsContent>
					<TabsContent value="auto">
						<AutoAddTab />
					</TabsContent>
					<TabsContent value="atlases">
						<AtlasesTab />
					</TabsContent>
					<TabsContent value="view">
						<ViewTab />
					</TabsContent>
					<TabsContent value="route">
						<RouteTab />
					</TabsContent>
					<TabsContent value="log" className="h-full">
						<LogTab />
					</TabsContent>
					{debug && (
						<TabsContent value="debug">
							<DebugTab />
						</TabsContent>
					)}
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
