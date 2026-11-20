import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Section } from "@/components/common/Section";
import { Button } from "@/components/ui/button";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppStore } from "@/store/AppStore";

/** Find's results: click one to go there and select it; Bookmark all puts them in one group. */
export function ResultList() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const results = useAppStore((s) => s.results);
	const title = useAppStore((s) => s.resultsTitle);
	const query = useAppStore((s) => s.query);
	const flyTo = useAppStore((s) => s.flyTo);
	const ask = useAppStore((s) => s.ask);
	const showError = useAppStore((s) => s.showError);
	const selectLoaded = useAppStore((s) => s.selectLoaded);
	const items = results.filter((r) => r.kind !== "bookmark");

	// a new list (a type clicked, a search): the panel scrolls down to show it (user)
	const box = useRef<HTMLDivElement>(null);
	useEffect(() => {
		if (title) box.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
	}, [title]);

	if (!title) return null;
	return (
		<div ref={box}>
			<Section
				title="Results"
				actions={
					items.length > 0 && (
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
					)
				}
			>
				<p className="text-xs text-muted-foreground">{title}</p>
				<ul className="max-h-80 overflow-y-auto">
					{results.slice(0, 500).map((r) => (
						<li key={`${r.kind}-${r.id}`}>
							<button
								type="button"
								className="flex min-h-8 w-full items-center truncate rounded px-2 text-left text-sm hover:bg-accent"
								onClick={async () => {
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
					{results.length > 500 && (
						<li className="px-2 py-1 text-muted-foreground">{results.length - 500} more: narrow the search</li>
					)}
				</ul>
			</Section>
		</div>
	);
}
