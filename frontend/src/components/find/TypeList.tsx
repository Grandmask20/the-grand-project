import { useQueryClient } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { IconPicture } from "@/components/common/IconPicture";
import { Checkbox } from "@/components/ui/checkbox";
import type { AppState } from "@/domain/app/AppState";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useTypes } from "@/hooks/find/UseTypes";

/** Places and map icons with their counts: tick to show on the map, click a name to list them all. */
export function TypeList({ onList }: { onList: (label: string, icon: string | null) => void }) {
	const types = useTypes();
	const settings = useSettings();
	const update = useUpdateSettings();
	const queryClient = useQueryClient();
	const hidden = new Set(settings?.hidden_types ?? []);
	const all = types.data?.sections.flatMap((s) => s.rows.map((r) => r.label)) ?? [];

	const set = (label: string, shown: boolean) => {
		// from the page's settings as they are now, not as this list last drew them (quick ticks: one was lost)
		const now = queryClient.getQueryData<AppState>(AppQueryKeys.state)?.settings.hidden_types;
		const next = new Set(now ?? hidden);
		if (shown) next.delete(label);
		else next.add(label);
		update.mutate({ hidden_types: [...next] });
	};

	if (!types.data?.sections.length) return <p className="text-muted-foreground">Nothing found yet.</p>;
	return (
		<div className="flex flex-col gap-1">
			<div className="flex gap-4 text-xs">
				<button type="button" className="text-gold hover:underline" onClick={() => update.mutate({ hidden_types: [] })}>
					Show all
				</button>
				<button
					type="button"
					className="text-gold hover:underline"
					onClick={() => update.mutate({ hidden_types: all })}
				>
					Hide all
				</button>
			</div>
			{/* in the panel's own scroll (PO's canvas: no box in a box; the results are above the types now) */}
			{types.data.sections.map((sec) => (
				<div key={sec.title} className="flex flex-col">
					<div className="pt-3 pb-1 text-xs font-medium text-muted-foreground">{sec.title}</div>
					{sec.rows.map((row) => (
						<div key={row.label} className="flex min-h-8 items-center gap-2.5 rounded px-1 hover:bg-accent">
							<Checkbox
								checked={!hidden.has(row.label)}
								onCheckedChange={(v) => set(row.label, v === true)}
								aria-label={`Show ${row.label}`}
							/>
							<IconPicture name={row.icon} />
							<button
								type="button"
								className="flex flex-1 items-center gap-2 truncate text-left text-sm"
								title={row.aliases || row.label}
								onClick={() => onList(row.label, sec.title === "Map icons" ? row.icon : null)}
							>
								<span className="flex-1 truncate">{row.label}</span>
								<span className="text-xs text-muted-foreground">{row.count}</span>
							</button>
						</div>
					))}
				</div>
			))}
		</div>
	);
}
