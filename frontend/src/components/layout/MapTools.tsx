import {
	LassoIcon,
	type LucideIcon,
	MapPinPlusIcon,
	MousePointer2Icon,
	MoveIcon,
	NavigationIcon,
	RouteIcon,
} from "lucide-react";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAtlasActions } from "@/hooks/atlas/UseAtlasActions";
import { type MapMode, useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

type Tool = { kind: MapMode["kind"]; label: string; title: string; Icon: LucideIcon; start: () => void };

/**
 * What a click on the map does, in the top bar (PO: the map tools were a big dock over the map): select, a route, a
 * bookmark, your position, the biome of maps, a screenshot placed by hand. The tool on is lit; clicked again, or
 * Select, ends it. None while the timelapse is open (it takes the map).
 */
export function MapTools() {
	const state = useAppState().data;
	const mode = useAppStore((s) => s.mode);
	const setMode = useAppStore((s) => s.setMode);
	const replay = useAppStore((s) => !!s.replay);
	const actions = useAtlasActions();
	const open = !!state?.atlas;
	const end = () => setMode({ kind: "normal" });

	const tools: Tool[] = [
		{
			kind: "normal",
			label: "Select",
			title: "Select: a click shows what is there",
			Icon: MousePointer2Icon,
			start: end,
		},
		{
			kind: "route",
			label: "Route",
			title: "Route: click the map it starts from, then the one it goes to",
			Icon: RouteIcon,
			start: () => setMode({ kind: "route", from: null }),
		},
		{
			kind: "bookmark",
			label: "Bookmark",
			title: "Add a bookmark: click a map, or a spot",
			Icon: MapPinPlusIcon,
			start: () => setMode({ kind: "bookmark" }),
		},
		{
			kind: "player",
			label: "I am here",
			title: "Set my position: click the map you are on",
			Icon: NavigationIcon,
			start: () => setMode({ kind: "player" }),
		},
		{
			kind: "lasso",
			// (not "City biome": strongholds aren't cities, user)
			label: "Biome",
			title: "Biome select: draw around maps, then pick their city type, a Breach stronghold, or none",
			Icon: LassoIcon,
			start: () => setMode({ kind: "lasso" }),
		},
		{
			kind: "ghost",
			label: "Place",
			title: "Place a screenshot by hand",
			Icon: MoveIcon,
			start: actions.askPlaceByHand,
		},
	];

	return (
		<div role="toolbar" aria-label="Map tools" className="ml-2 flex gap-0.5 rounded-md border bg-background p-0.5">
			{tools.map((t) => {
				const on = t.kind === "normal" ? mode.kind === "normal" : mode.kind === t.kind;
				return (
					<button
						key={t.kind}
						type="button"
						title={t.title}
						aria-pressed={on}
						disabled={t.kind !== "normal" && (!open || replay)}
						onClick={on && t.kind !== "normal" ? end : t.start}
						className={cn(
							"flex h-7 items-center gap-1.5 rounded px-2 text-xs font-medium whitespace-nowrap disabled:opacity-45",
							on ? "bg-gold text-background" : "text-muted-foreground hover:bg-accent hover:text-foreground",
						)}
					>
						<t.Icon className="size-4" aria-hidden />
						{t.label}
					</button>
				);
			})}
		</div>
	);
}
