import { RouteIcon } from "lucide-react";
import { mapsLeft, routeDone } from "@/hooks/map/UseRoutes";
import { cn } from "@/utils/Cn";
import { plural } from "@/utils/Format";

/**
 * A route tracked, as a card (banner's #51, liked by the user): "map #350 → map #225", how many maps it runs and how
 * many are left, and a bar of how far along it is. `bare`: only the lines and the bar (inside a bookmark's row).
 */
export function RouteProgress({ path, at, bare = false }: { path: number[]; at: number; bare?: boolean }) {
	const maps = new Set(path).size;
	const left = mapsLeft(path, at);
	const done = routeDone(path, at);
	const ends = `map #${path[0]} → map #${path[path.length - 1]}`;
	return (
		<div className={cn("flex flex-col gap-1", !bare && "rounded-md border bg-[var(--well)] p-3")}>
			{!bare && (
				<span className="flex items-center gap-2 text-sm font-medium">
					<RouteIcon className="size-4 shrink-0 text-route" aria-hidden />
					{ends}
				</span>
			)}
			<span className="text-xs text-muted-foreground">
				{bare && `${ends} · `}
				{plural(maps, "map")} · {left > 0 ? `${left} left` : "last map"}
			</span>
			<span
				className="mt-1 block h-1.5 overflow-hidden rounded bg-border"
				role="progressbar"
				aria-valuemin={0}
				aria-valuemax={100}
				aria-valuenow={Math.round(done * 100)}
				aria-label="How far along the route"
			>
				<span className="block h-full rounded bg-route" style={{ width: `${done * 100}%` }} />
			</span>
		</div>
	);
}
