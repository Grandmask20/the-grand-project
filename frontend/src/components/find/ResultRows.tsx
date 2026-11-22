import { useQueryClient } from "@tanstack/react-query";
import { BookmarkIcon } from "lucide-react";
import { useState } from "react";
import { sameAtlas } from "@/api/Http";
import { IconPicture } from "@/components/common/IconPicture";
import { Button } from "@/components/ui/button";
import type { ResultIcon, ResultRow } from "@/domain/find/SearchResult";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";

/** How many rows a list shows at most (more: narrow the search). */
const ROWS_MAX = 500;
/** How many icon kinds a row shows before "+n". */
const ICON_KINDS = 4;

/** A map's icons by kind, each with how many of it (user's mockup: the icons grouped, with their count). */
export function iconGroups(icons: ResultIcon[]): (ResultIcon & { count: number })[] {
	const by = new Map<string, ResultIcon & { count: number }>();
	for (const ic of icons) {
		const had = by.get(ic.name);
		if (had) had.count++;
		else by.set(ic.name, { ...ic, count: 1 });
	}
	return [...by.values()];
}

/** The text a row shows when pointed at: its name, where it is, its map's icons. */
export function rowTitle(r: ResultRow): string {
	const icons = (r.icons ?? []).map((i) => i.label);
	return [r.label, r.note, icons.length ? `map icons: ${[...new Set(icons)].join(", ")}` : ""]
		.filter(Boolean)
		.join(" · ");
}

/** The ground around a result: the map node itself, as the map shows it (user's mockup: the map it is on, not the
 * icon over it; a tower where it is); nothing while none. */
function Crop({ r }: { r: ResultRow }) {
	const app = useAppClient();
	const state = useAppState().data;
	const [failed, setFailed] = useState(false);
	const gen = state?.generation;
	if (gen === undefined || failed) return <span className="size-9 shrink-0 rounded border bg-map" aria-hidden="true" />;
	return (
		<img
			src={app.cropUrl(r.at?.[0] ?? r.x, r.at?.[1] ?? r.y, gen, state?.terrain_version ?? 0)}
			alt=""
			width={36}
			height={36}
			loading="lazy"
			onError={() => setFailed(true)}
			className="size-9 shrink-0 rounded border bg-map object-cover"
		/>
	);
}

/**
 * Find's result rows inside the list (user: never over it, nor dropping down under the search): the ground around
 * each, its name and where it is, its map's icons grouped with their counts. A click goes there and selects it.
 */
export function ResultRows({ rows }: { rows: ResultRow[] }) {
	const app = useAppClient();
	const flyTo = useAppStore((s) => s.flyTo);
	const showError = useAppStore((s) => s.showError);
	const selectLoaded = useAppStore((s) => s.selectLoaded);
	if (!rows.length) return <p className="px-2 py-1 text-xs text-muted-foreground">Nothing found.</p>;
	return (
		<ul className="flex flex-col" aria-label="Results">
			{rows.slice(0, ROWS_MAX).map((r) => {
				const groups = iconGroups(r.icons ?? []);
				return (
					<li key={`${r.kind}-${r.id}`}>
						<button
							type="button"
							title={rowTitle(r)}
							className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left hover:bg-accent"
							onClick={async () => {
								flyTo(r.x, r.y, 1);
								try {
									await selectLoaded(app.getInfo(r.kind, r.id));
								} catch (e) {
									showError(e);
								}
							}}
						>
							<Crop r={r} />
							<span className="flex min-w-0 flex-1 flex-col">
								<span className="flex items-center gap-1 truncate">
									{r.icon && <IconPicture name={r.icon} size={16} />}
									<span className="truncate">{r.label}</span>
									{r.bookmarked && <BookmarkIcon className="size-3.5 shrink-0 text-gold" aria-label="bookmarked" />}
								</span>
								{r.note && <span className="truncate text-xs text-muted-foreground">{r.note}</span>}
							</span>
							{groups.length > 0 && (
								<span className="flex shrink-0 items-center gap-1">
									{groups.slice(0, ICON_KINDS).map((g) => (
										<span key={g.name} className="flex items-center">
											<IconPicture name={g.name} size={18} />
											{g.count > 1 && <span className="text-xs text-muted-foreground">×{g.count}</span>}
										</span>
									))}
									{groups.length > ICON_KINDS && (
										<span className="text-xs text-muted-foreground">+{groups.length - ICON_KINDS}</span>
									)}
								</span>
							)}
						</button>
					</li>
				);
			})}
			{rows.length > ROWS_MAX && (
				<li className="px-2 py-1 text-xs text-muted-foreground">{rows.length - ROWS_MAX} more: narrow the search</li>
			)}
		</ul>
	);
}

/** Bookmark all of a list's results into one group (asked for its name first). */
export function BookmarkAll({ rows, name }: { rows: ResultRow[]; name: string }) {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const ask = useAppStore((s) => s.ask);
	const showError = useAppStore((s) => s.showError);
	const items = rows.filter((r) => r.kind !== "bookmark");
	if (!items.length) return null;
	return (
		<Button
			size="xs"
			variant="outline"
			onClick={(e) => {
				e.stopPropagation();
				// the results are this atlas's: answered after a switch, nothing is bookmarked (the prompt goes with the
				// atlas too: resetAtlas)
				const same = sameAtlas();
				ask({
					title: "Bookmark all",
					label: `Bookmark all ${items.length} results into group:`,
					value: name,
					onOk: (group) =>
						same() &&
						void app
							.bookmarkAll(
								items.map((r) => ({ kind: r.kind, id: r.id })),
								group || "Other",
							)
							.then(() => queryClient.invalidateQueries({ queryKey: ["bookmarks"] }))
							.catch(showError),
				});
			}}
		>
			Bookmark all
		</Button>
	);
}
