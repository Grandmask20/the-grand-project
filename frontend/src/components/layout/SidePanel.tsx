import { AutoAddTab } from "@/components/adding/AutoAddTab";
import { AtlasesTab } from "@/components/atlases/AtlasesTab";
import { BookmarksTab } from "@/components/bookmarks/BookmarksTab";
import { DebugTab } from "@/components/debug/DebugTab";
import { FindTab } from "@/components/find/FindTab";
import { LogTab } from "@/components/log/LogTab";
import { RouteTab } from "@/components/route/RouteTab";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ViewTab } from "@/components/view/ViewTab";
import { useAppStore } from "@/store/AppStore";

const TABS: [string, string][] = [
	["find", "Find"],
	["bookmarks", "Bookmarks"],
	["auto", "Auto-add"],
	["atlases", "Atlases"],
	["view", "View"],
	["route", "Route"],
	["log", "Log"],
];

/** The side panel's tabs. */
export function SidePanel({ debug }: { debug: boolean }) {
	const tab = useAppStore((s) => s.tab);
	const setTab = useAppStore((s) => s.setTab);
	const tabs = debug ? [...TABS, ["debug", "Debug"] as [string, string]] : TABS;
	return (
		<aside className="flex h-full w-[400px] shrink-0 flex-col border-r bg-background">
			<Tabs value={tab} onValueChange={setTab} className="flex h-full min-h-0 flex-col">
				<TabsList className="m-2 mb-0 flex h-auto w-auto flex-wrap">
					{tabs.map(([k, label]) => (
						<TabsTrigger key={k} value={k}>
							{label}
						</TabsTrigger>
					))}
				</TabsList>
				<div className="min-h-0 flex-1 overflow-y-auto p-3">
					<TabsContent value="find">
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
		</aside>
	);
}
