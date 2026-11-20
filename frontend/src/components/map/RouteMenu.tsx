import { useRef } from "react";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { plural } from "@/utils/Format";

interface Props {
	x: number;
	y: number;
	from: number;
	to: number;
	maps: number;
	onChoose: (what: "track" | "save" | null) => void;
}

/** After the second map of a route (Route in the top bar): track it now, or save it with the bookmarks (user). */
export function RouteMenu({ x, y, from, to, maps, onChoose }: Props) {
	// picking an item also closes the menu, and closing counts as Cancel: answered once, the first answer stands
	// (Track now was followed by a Cancel that cleared the route)
	const answered = useRef(false);
	const answer = (what: "track" | "save" | null) => {
		if (answered.current) return;
		answered.current = true;
		onChoose(what);
	};
	return (
		<DropdownMenu open onOpenChange={(open) => !open && answer(null)}>
			<DropdownMenuTrigger asChild>
				<span className="pointer-events-none absolute size-px" style={{ left: x, top: y }} />
			</DropdownMenuTrigger>
			<DropdownMenuContent align="start">
				<DropdownMenuLabel>
					Map #{from} → map #{to}: {plural(maps, "map")}
				</DropdownMenuLabel>
				<DropdownMenuItem onSelect={() => answer("track")}>Track now</DropdownMenuItem>
				<DropdownMenuItem onSelect={() => answer("save")}>Save route…</DropdownMenuItem>
				<DropdownMenuSeparator />
				<DropdownMenuItem onSelect={() => answer(null)}>Cancel</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
