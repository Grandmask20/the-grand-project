import { useQueryClient } from "@tanstack/react-query";
import { type KeyboardEvent, useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppStore } from "@/store/AppStore";

/**
 * Find's results: a list that drops down under the search, as the route's "to the nearest map with…" does (user).
 * Click one to go there and select it (the list closes); Bookmark all puts them in one group; ↑ ↓ move between them.
 */
export function ResultList({ onPick }: { onPick?: () => void }) {
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
	// the kinds Find's pills show (a path, which has no pill, always)
	const rows = results.filter((r) => r.kind === "path" || kinds.includes(r.kind));
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
			</div>
			<ul className="max-h-96 overflow-y-auto" onKeyDown={move}>
				{rows.slice(0, 500).map((r) => (
					<li key={`${r.kind}-${r.id}`}>
						<button
							type="button"
							className="flex min-h-8 w-full items-center truncate rounded-sm px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent"
							onClick={async () => {
								onPick?.();
								flyTo(r.x, r.y, 1);
								try {
									await selectLoaded(app.getInfo(r.kind, r.id));
								} catch (e) {
									showError(e);
								}
							}}
						>
							{r.label}
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
