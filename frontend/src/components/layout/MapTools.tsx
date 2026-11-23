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

type Tool = { kind: MapMode["kind"]; label: string; title: string; Icon: LucideIcon; start: () => void };

/**
 * What a click on the map does, as tabs in the top bar (banner's #51 had the idea; the user's design: PoE's stash
 * tabs, every tool named, the one on lit and open into the bar under it): select, a route, a bookmark, your position,
 * the biome of maps, a screenshot placed by hand. Clicked again, a tool on ends (as Select or Esc do). None but Select
 * while the timelapse is open (it takes the map) or with no atlas.
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
			label: "I'm here",
			title: "Set your position: click the map you are on",
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
		<div role="toolbar" aria-label="Map tools" className="poe-tools">
			<span className="poe-bar" aria-hidden="true" />
			{tools.map((t) => {
				// (Select is on while no other tool is: route-edit and the debug link are Bookmarks' and Debug's own)
				const on =
					t.kind === "normal" ? !tools.some((o) => o.kind !== "normal" && o.kind === mode.kind) : mode.kind === t.kind;
				return (
					<button
						key={t.kind}
						type="button"
						aria-label={t.label}
						title={t.title}
						aria-pressed={on}
						data-on={on || undefined}
						disabled={t.kind !== "normal" && (!open || replay)}
						onClick={on && t.kind !== "normal" ? end : t.start}
						className="poe-tab"
					>
						<t.Icon className="size-4" aria-hidden />
						<span className="max-[1180px]:hidden">{t.label}</span>
					</button>
				);
			})}
		</div>
	);
}
