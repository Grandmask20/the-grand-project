import { useQueryClient } from "@tanstack/react-query";
import { ChevronDownIcon, ChevronRightIcon, XIcon } from "lucide-react";
import { useEffect, useRef } from "react";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { IconPicture } from "@/components/common/IconPicture";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import type { AppState } from "@/domain/app/AppState";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useTypes } from "@/hooks/find/UseTypes";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";
import { BookmarkAll, ResultRows } from "./ResultRows";

/**
 * Find's list, down to the panel's bottom: places and map icons with their counts (tick to show on the map), and
 * the results in it, never over it (user: no results dropping down under the search; a type clicked opens its
 * results within the list, as a bookmark group does). A search's results are the first group while it is typed.
 */
export function TypeList({ onList }: { onList: (label: string, icon: string | null) => void }) {
	const types = useTypes();
	const settings = useSettings();
	const update = useUpdateSettings();
	const queryClient = useQueryClient();
	const query = useAppStore((s) => s.query);
	const listed = useAppStore((s) => s.listed);
	const results = useAppStore((s) => s.results);
	const title = useAppStore((s) => s.resultsTitle);
	const clear = useAppStore((s) => s.clearFind);
	const hidden = new Set(settings?.hidden_types ?? []);
	const all = types.data?.sections.flatMap((s) => s.rows.map((r) => r.label)) ?? [];
	const searching = query.trim().length > 0;
	const open = searching ? null : (listed?.label ?? null);

	const set = (label: string, shown: boolean) => {
		// from the page's settings as they are now, not as this list last drew them (quick ticks: one was lost)
		const now = queryClient.getQueryData<AppState>(AppQueryKeys.state)?.settings.hidden_types;
		const next = new Set(now ?? hidden);
		if (shown) next.delete(label);
		else next.add(label);
		update.mutate({ hidden_types: [...next] });
	};

	// a group opened (a type clicked, a search) once its results are in: a type's row rises to the list's middle at
	// least (user: opened low down, one result showed), and comes down into view if above it. A search's group is the
	// list's first: the list goes back to its top (scrolled down among the types, the browser kept the list where it
	// was, the results out of sight above: app check)
	const openRow = useRef<HTMLDivElement>(null);
	const box = useRef<HTMLDivElement>(null);
	useEffect(() => {
		const b = box.current;
		if (!title || !b) return;
		if (searching) {
			b.scrollTop = 0;
			return;
		}
		const row = openRow.current;
		if (!row) return;
		const at = row.getBoundingClientRect().top - b.getBoundingClientRect().top; // (from the list's visible top)
		const by = at < 0 ? at : at > b.clientHeight / 2 ? at - b.clientHeight / 2 : 0;
		if (by) b.scrollTop += by;
	}, [title, searching]);

	return (
		<div className="flex min-h-64 flex-1 flex-col gap-2">
			{types.data?.sections.length ? (
				<div className="flex gap-2">
					<Button size="xs" variant="outline" onClick={() => update.mutate({ hidden_types: [] })}>
						Show all
					</Button>
					<Button size="xs" variant="outline" onClick={() => update.mutate({ hidden_types: all })}>
						Hide all
					</Button>
				</div>
			) : null}
			<div ref={box} className="poe-frame min-h-0 flex-1 overflow-y-auto bg-[var(--well)] p-1 [overflow-anchor:none]">
				{searching && (
					<div ref={openRow} className="mb-1 flex flex-col border-b pb-1">
						{/* its header stays at the list's top while its results scroll under it, so it can be cleared
						    from anywhere in them (user) */}
						<div className="sticky -top-1 z-10 flex items-center gap-2 border-b bg-[var(--well)] px-1 py-1">
							<ChevronDownIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
							<span className="min-w-0 flex-1 truncate text-sm font-semibold">
								{title || `Finding "${query.trim()}"…`}
							</span>
							{title && <BookmarkAll rows={results} name={query.trim()} />}
							<button
								type="button"
								aria-label="Clear the search"
								title="Clear the search and the rings on the map (Esc)"
								onClick={clear}
								className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
							>
								<XIcon className="size-4" />
							</button>
						</div>
						{title && results.length > 0 && <ResultRows rows={results} />}
					</div>
				)}
				{!types.data?.sections.length && !searching && <p className="p-1 text-muted-foreground">Nothing found yet.</p>}
				{types.data?.sections.map((sec) => (
					<div key={sec.title} className="flex flex-col">
						<div className="px-1 py-1 text-xs font-semibold text-muted-foreground">{sec.title}</div>
						{sec.rows.map((row) => {
							const isOpen = open === row.label;
							const Chevron = isOpen ? ChevronDownIcon : ChevronRightIcon;
							return (
								<div key={row.label} className={isOpen ? "my-1 flex flex-col rounded bg-muted/40" : "flex flex-col"}>
									{/* open: its header stays at the list's top while its results scroll under it, so it can
									    be folded from anywhere in them (user) */}
									<div
										ref={isOpen ? openRow : undefined}
										className={cn(
											"flex items-center gap-2 rounded px-1 py-0.5 hover:bg-accent",
											isOpen && "sticky -top-1 z-10 rounded-none border-b bg-[var(--well)]",
										)}
									>
										<Checkbox
											checked={!hidden.has(row.label)}
											onCheckedChange={(v) => set(row.label, v === true)}
											aria-label={`Show ${row.label}`}
										/>
										<IconPicture name={row.icon} />
										<button
											type="button"
											aria-expanded={isOpen}
											className="flex min-w-0 flex-1 items-center gap-1 text-left"
											title={row.aliases || row.label}
											// open: its results under it; again: folded (and its rings off the map)
											onClick={() =>
												isOpen ? clear() : onList(row.label, sec.title === "Map icons" ? row.icon : null)
											}
										>
											<span className="truncate">{row.label}</span>
											<span className="text-muted-foreground">({row.count})</span>
											<Chevron className="ml-auto size-4 shrink-0 text-muted-foreground" aria-hidden />
										</button>
										{isOpen && title && <BookmarkAll rows={results} name={row.label} />}
									</div>
									{isOpen && (
										<div className="pb-1 pl-6">
											{title ? <ResultRows rows={results} /> : <p className="px-2 py-1 text-xs">Loading…</p>}
										</div>
									)}
								</div>
							);
						})}
					</div>
				))}
			</div>
		</div>
	);
}
