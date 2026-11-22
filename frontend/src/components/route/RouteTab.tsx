import { CheckIcon, NavigationIcon } from "lucide-react";
import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTypes } from "@/hooks/find/UseTypes";
import { nextNew, useRoutes } from "@/hooks/map/UseRoutes";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { RouteProgress } from "./RouteProgress";

/** Directions: where you are, the fewest maps to a map or to the nearest map with an icon. */
export function RouteTab() {
	const routes = useRoutes();
	const route = useAppStore((s) => s.route);
	// the next map not run yet (a branch is run there and back: the maps on the way back are run already)
	const next = route?.at !== undefined ? nextNew(route.path, route.at) : null;
	const runSet = new Set(route?.at !== undefined ? route.path.slice(0, route.at + 1) : []); // (the maps run)
	const mode = useAppStore((s) => s.mode);
	const setMode = useAppStore((s) => s.setMode);
	const flyTo = useAppStore((s) => s.flyTo);
	const highlight = useAppStore((s) => s.highlight);
	const setHighlight = useAppStore((s) => s.setHighlight);
	const icons = useTypes().data?.sections.find((s) => s.title === "Map icons")?.rows ?? [];
	const iconOf = new Map(icons.map((r) => [r.icon, r.label]));

	return (
		<div className="flex flex-col gap-5">
			<Section title="You are here">
				<p>{routes.player ? <>map #{routes.player.node}</> : <span className="text-muted-foreground">not set</span>}</p>
				<div className="flex gap-1.5">
					<Button
						size="xs"
						variant={mode.kind === "player" ? "default" : "outline"}
						onClick={() => setMode({ kind: "player" })}
					>
						Set my position
					</Button>
					{routes.player && (
						<Button
							size="xs"
							variant="outline"
							onClick={() => flyTo(routes.player?.x ?? 0, routes.player?.y ?? 0, 0.5)}
						>
							Go there
						</Button>
					)}
					{routes.player && (
						<Button size="xs" variant="outline" onClick={routes.clearPlayer}>
							Forget my position
						</Button>
					)}
				</div>
				{mode.kind === "player" && <p className="text-xs text-gold">Click the map you are on (Esc cancels).</p>}
			</Section>

			<Section title="Highlight">
				<Select value={highlight ?? "none"} onValueChange={(v) => setHighlight(v === "none" ? null : v)}>
					<SelectTrigger size="sm" aria-label="Highlight maps with">
						<SelectValue placeholder="maps with…" />
					</SelectTrigger>
					<SelectContent>
						<SelectItem value="none">nothing</SelectItem>
						{icons.map((r) => (
							<SelectItem key={r.icon} value={r.icon}>
								{r.label} ({r.count})
							</SelectItem>
						))}
					</SelectContent>
				</Select>
			</Section>

			<Section title="Route">
				<Select value="" onValueChange={(v) => routes.routeToNearest(v, iconOf.get(v))}>
					<SelectTrigger size="sm" aria-label="Route to the nearest">
						<SelectValue placeholder="to the nearest map with…" />
					</SelectTrigger>
					<SelectContent>
						{icons.map((r) => (
							<SelectItem key={r.icon} value={r.icon}>
								{r.label}
							</SelectItem>
						))}
					</SelectContent>
				</Select>
				<p className="text-xs text-muted-foreground">Or right-click a map: Route here. Or Route in the top bar.</p>
				{/* no route: why (set your position first, no path) */}
				{route && route.at === undefined && <p className="font-medium">{route.message}</p>}
			</Section>

			{/* the route tracked, however it was found (Route here, the nearest map, Route in the top bar, a saved route):
			    how many maps are left, on to the next, and its maps (user: Route here and tracking worked apart) */}
			{route?.at !== undefined && (
				<Section title="Tracking">
					<RouteProgress path={route.path} at={route.at} />
					<div className="flex gap-1.5">
						<Button size="xs" disabled={next === null} onClick={routes.nextMap}>
							Next map
						</Button>
						<Button size="xs" variant="outline" onClick={routes.clear}>
							Stop tracking
						</Button>
					</div>
					{/* the route as steps (banner's #51, liked by the user): run, where you are, next, still to come */}
					<ol aria-label="The route's maps" className="flex max-h-80 flex-col overflow-y-auto">
						{[...new Set(route.path)].map((id, k) => {
							const p = routes.graph?.at(id);
							const what = (routes.graph?.iconsOf(id) ?? []).map((n) => iconOf.get(n) ?? n).join(", ");
							const here = id === route.path[route.at ?? 0];
							const run = runSet.has(id) && !here;
							const isNext = next !== null && id === route.path[next];
							return (
								<li key={id}>
									<button
										type="button"
										title={what ? `map #${id} · ${what}` : `map #${id}`}
										onClick={() => p && flyTo(p[0], p[1], 0.6)}
										className={cn(
											"flex min-h-8 w-full items-center gap-2.5 rounded px-1.5 text-left text-sm hover:bg-accent",
											here && "bg-accent",
											run && "text-muted-foreground",
										)}
									>
										<span
											className={cn(
												"flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
												here
													? "bg-gold text-background"
													: run
														? "bg-muted text-muted-foreground"
														: "border border-border text-muted-foreground",
											)}
											title={here ? "you are here" : run ? "run" : undefined}
										>
											{here ? <NavigationIcon className="size-3" /> : run ? <CheckIcon className="size-3" /> : k}
										</span>
										<span className={cn("flex-1", run && "line-through")}>
											map #{id}
											{k === 0 && <span className="text-muted-foreground"> · start</span>}
										</span>
										{isNext && <span className="rounded bg-muted px-1.5 text-xs font-semibold text-gold">next</span>}
										{what && <span className="max-w-32 truncate text-xs text-muted-foreground">{what}</span>}
									</button>
								</li>
							);
						})}
					</ol>
				</Section>
			)}
		</div>
	);
}
