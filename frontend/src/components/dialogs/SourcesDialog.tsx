import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSources } from "@/hooks/find/UseSources";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** The screenshots that show a spot, best view first, the spot circled on the one picked. */
export function SourcesDialog() {
	const app = useAppClient();
	const spot = useAppStore((s) => s.sources);
	const close = useAppStore((s) => s.showSources);
	const sources = useSources(spot);
	const [k, setK] = useState(0);
	// biome-ignore lint/correctness/useExhaustiveDependencies: back to the first screenshot for another spot
	useEffect(() => setK(0), [spot]);

	if (!spot) return null;
	const list = sources.data ?? [];
	const shot = list[k];
	return (
		<Dialog open onOpenChange={(open) => !open && close(null)}>
			<DialogContent className="h-[80vh] sm:max-w-6xl">
				<DialogHeader>
					<DialogTitle>
						Screenshots of {spot[0].toFixed(0)}, {spot[1].toFixed(0)}
					</DialogTitle>
				</DialogHeader>
				{sources.isSuccess && !list.length && <p className="text-muted-foreground">No screenshot covers that spot.</p>}
				{sources.isError && (
					<p className="text-destructive">
						The screenshots could not be listed: {sources.error instanceof Error ? sources.error.message : "error"}
					</p>
				)}
				{list.length > 0 && (
					<div className="flex min-h-0 flex-1 gap-3">
						<ul className="w-48 shrink-0 overflow-y-auto rounded border text-sm">
							{list.map((s, i) => (
								<li key={s.name}>
									<button
										type="button"
										className={cn(
											"w-full truncate px-2 py-1 text-left hover:bg-accent",
											i === k && "bg-accent text-gold",
										)}
										onClick={() => setK(i)}
									>
										{s.name}
									</button>
								</li>
							))}
						</ul>
						<div className="relative flex min-w-0 flex-1 items-center justify-center overflow-hidden rounded bg-map">
							{shot && !shot.exists && <p className="text-muted-foreground">missing file: {shot.name}</p>}
							{shot?.exists && (
								<div className="relative max-h-full max-w-full" style={{ aspectRatio: `${shot.w} / ${shot.h}` }}>
									<img
										src={app.screenshotUrl(shot.name, 1600)}
										alt={shot.name}
										className="h-full w-full object-contain"
									/>
									<div
										className="absolute size-11 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-highlight"
										style={{ left: `${(shot.px / shot.w) * 100}%`, top: `${(shot.py / shot.h) * 100}%` }}
									/>
								</div>
							)}
						</div>
					</div>
				)}
			</DialogContent>
		</Dialog>
	);
}
