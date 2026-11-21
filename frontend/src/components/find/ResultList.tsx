import { useQueryClient } from "@tanstack/react-query";
import { BookmarkIcon, CastleIcon, SplineIcon, XIcon } from "lucide-react";
import { type KeyboardEvent, useEffect, useRef } from "react";
import { IconPicture } from "@/components/common/IconPicture";
import { MapMark } from "@/components/common/MapMark";
import { Button } from "@/components/ui/button";
import type { ResultRow } from "@/domain/find/SearchResult";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppStore } from "@/store/AppStore";

/** A row's tooltip: its name, where it is, its map's icons by name. */
function rowTooltip(r: ResultRow): string {
	const icons = [...new Set((r.icons ?? []).map((ic) => ic.label))].join(", ");
	return [r.label, r.note, icons && `map icons: ${icons}`].filter(Boolean).join(" · ");
}

/** What a result is, as a picture: an icon's or a place's own, a map's art, or a sign (user: "icon  text"). */
function RowPicture({ row }: { row: ResultRow }) {
	const inner = row.icon ? (
		<IconPicture name={row.icon} size={22} />
	) : row.kind === "node" ? (
		<MapMark size={20} />
	) : row.kind === "bookmark" ? (
		<BookmarkIcon className="size-4 text-gold" />
	) : row.kind === "landmark" ? (
		<CastleIcon className="size-4 text-gold" />
	) : (
		<SplineIcon className="size-4 text-gold" />
	);
	return <span className="flex size-6 shrink-0 items-center justify-center">{inner}</span>;
}

/** The icons of a result's map, on its right (user: a map lists all its icons); an icon's own is its picture, not
 * here again. Their names are in the row's tooltip. */
function MapIcons({ row }: { row: ResultRow }) {
	// each icon once (a map with two of one icon shows it once)
	const seen = new Set(row.kind === "icon" && row.icon ? [row.icon] : []);
	const icons = (row.icons ?? []).filter((ic) => !seen.has(ic.name) && seen.add(ic.name));
	if (!icons.length) return null;
	return (
		<span className="flex shrink-0 items-center gap-0.5">
			{icons.slice(0, 5).map((ic) => (
				<span key={ic.name} title={ic.label} aria-hidden>
					<IconPicture name={ic.name} size={18} />
				</span>
			))}
			{icons.length > 5 && (
				<span className="text-xs text-muted-foreground" aria-hidden>
					+{icons.length - 5}
				</span>
			)}
		</span>
	);
}

/**
 * Find's results: a list that drops down under the search, as the route's "to the nearest map with…" does (user).
 * Click one to go there and select it, the list staying to go through the rest (user), the one selected lit; its ✕
 * closes it; Bookmark all puts them in one group; ↑ ↓ move between them.
 */
export function ResultList({ onClose }: { onClose?: () => void }) {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const results = useAppStore((s) => s.results);
	const title = useAppStore((s) => s.resultsTitle);
	const query = useAppStore((s) => s.query);
	const flyTo = useAppStore((s) => s.flyTo);
	const ask = useAppStore((s) => s.ask);
	const showError = useAppStore((s) => s.showError);
	const selectLoaded = useAppStore((s) => s.selectLoaded);
	const kinds = useAppStore((s) => s.findKinds);
	const sel = useAppStore((s) => (s.selected ? `${s.selected.kind}:${s.selected.id}` : ""));
	// the kinds Find's pills show (a path, which has no pill, always); a type's list (a type clicked) as asked: its
	// icons with Icons off too
	const listed = useAppStore((s) => s.listed && !s.query.trim());
	const rows = results.filter((r) => listed || r.kind === "path" || kinds.includes(r.kind));
	const items = rows.filter((r) => r.kind !== "bookmark");

	// a new list (a type clicked far below, a search): the panel scrolls up to show it (user)
	const box = useRef<HTMLElement>(null);
	useEffect(() => {
		if (title) box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
	}, [title]);

	// ↑ ↓ between the results (the search's ↓ comes to the first)
	const move = (e: KeyboardEvent<HTMLUListElement>) => {
		if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
		e.preventDefault();
		const all = [...e.currentTarget.querySelectorAll<HTMLButtonElement>("button")];
		const at = all.indexOf(document.activeElement as HTMLButtonElement);
		all[Math.max(0, Math.min(all.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
	};

	if (!title) return null;
	return (
		<section
			ref={box}
			aria-label="Results"
			className="absolute top-full right-0 left-0 z-50 mt-1 rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
		>
			<div className="flex items-center gap-2 px-2 py-1">
				<span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{title}</span>
				{items.length > 0 && (
					<Button
						size="xs"
						variant="outline"
						onClick={() =>
							ask({
								title: "Bookmark all",
								label: `Bookmark all ${items.length} results into group:`,
								value: query.trim(),
								onOk: (group) =>
									void app
										.bookmarkAll(
											items.map((r) => ({ kind: r.kind, id: r.id })),
											group || "Other",
										)
										.then(() => queryClient.invalidateQueries({ queryKey: ["bookmarks"] }))
										.catch(showError),
							})
						}
					>
						Bookmark all
					</Button>
				)}
				{onClose && (
					<button
						type="button"
						aria-label="Close the results"
						title="Close the results (the search opens them again)"
						onClick={onClose}
						className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
					>
						<XIcon className="size-4" />
					</button>
				)}
			</div>
			<ul className="max-h-96 overflow-y-auto" onKeyDown={move}>
				{rows.slice(0, 500).map((r) => (
					<li key={`${r.kind}-${r.id}`}>
						<button
							type="button"
							aria-label={r.label}
							aria-current={sel === `${r.kind}:${r.id}` || undefined}
							title={rowTooltip(r)}
							className="flex min-h-9 w-full items-center gap-2.5 rounded-sm px-2 py-1 text-left outline-none hover:bg-accent focus-visible:bg-accent aria-[current]:bg-accent aria-[current]:shadow-[inset_2px_0_0_var(--color-gold)]"
							onClick={async () => {
								flyTo(r.x, r.y, 1);
								try {
									await selectLoaded(app.getInfo(r.kind, r.id));
								} catch (e) {
									showError(e);
								}
							}}
						>
							<RowPicture row={r} />
							<span className="min-w-0 flex-1">
								<span className="block truncate text-sm">
									{r.label}
									{r.bookmarked && <span className="ml-1 text-gold">★</span>}
								</span>
								{r.note && <span className="block truncate text-xs text-muted-foreground">{r.note}</span>}
							</span>
							<MapIcons row={r} />
						</button>
					</li>
				))}
				{rows.length > 500 && (
					<li className="px-2 py-1 text-muted-foreground">{rows.length - 500} more: narrow the search</li>
				)}
				{rows.length < results.length && (
					<li className="px-2 py-1 text-xs text-muted-foreground">
						{results.length - rows.length} more of the kinds switched off under the search
					</li>
				)}
			</ul>
		</section>
	);
}
