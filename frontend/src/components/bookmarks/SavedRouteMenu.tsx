import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Bookmark, SavedRoute } from "@/domain/bookmarks/Bookmarks";
import { routeTitle, useRoutes } from "@/hooks/map/UseRoutes";
import { useAppStore } from "@/store/AppStore";

interface Props {
	x: number;
	y: number;
	bookmark: Bookmark & { route: SavedRoute };
	onClose: () => void;
}

/** A saved route's right-click menu in Bookmarks (user): track it now, or add maps to it / take maps off it by
 * clicking them on the map. */
export function SavedRouteMenu({ x, y, bookmark: b, onClose }: Props) {
	const routes = useRoutes(); // (the map's paths load when the menu opens)
	const lightRoute = useAppStore((s) => s.lightRoute);
	const setMode = useAppStore((s) => s.setMode);
	const showError = useAppStore((s) => s.showError);
	const edit = (add: boolean) => {
		lightRoute(b.id);
		setMode({ kind: "route-edit", id: b.id, add });
	};
	return (
		<DropdownMenu open onOpenChange={(open) => !open && onClose()}>
			<DropdownMenuTrigger asChild>
				<span className="pointer-events-none fixed size-px" style={{ left: x, top: y }} />
			</DropdownMenuTrigger>
			<DropdownMenuContent align="start">
				<DropdownMenuLabel>{routeTitle(b.name, b.route)}</DropdownMenuLabel>
				<DropdownMenuItem
					disabled={!routes.graph}
					onSelect={() => {
						if (!routes.trackSaved(b.route)) showError("This route's maps aren't on this atlas any more.", true);
					}}
				>
					Start tracking now
				</DropdownMenuItem>
				<DropdownMenuSeparator />
				<DropdownMenuItem onSelect={() => edit(true)}>Add maps</DropdownMenuItem>
				<DropdownMenuItem onSelect={() => edit(false)}>Remove maps</DropdownMenuItem>
			</DropdownMenuContent>
		</DropdownMenu>
	);
}
