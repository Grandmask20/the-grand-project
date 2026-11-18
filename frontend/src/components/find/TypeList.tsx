import { IconPicture } from "@/components/common/IconPicture";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useTypes } from "@/hooks/find/UseTypes";

/** Places and map icons with their counts: tick to show on the map, click a name to list them all. */
export function TypeList({ onList }: { onList: (label: string, icon: string | null) => void }) {
	const types = useTypes();
	const settings = useSettings();
	const update = useUpdateSettings();
	const hidden = new Set(settings?.hidden_types ?? []);
	const all = types.data?.sections.flatMap((s) => s.rows.map((r) => r.label)) ?? [];

	const set = (label: string, shown: boolean) => {
		const next = new Set(hidden);
		if (shown) next.delete(label);
		else next.add(label);
		update.mutate({ hidden_types: [...next] });
	};

	if (!types.data?.sections.length) return <p className="text-muted-foreground">Nothing found yet.</p>;
	return (
		<div className="flex flex-col gap-2">
			<div className="flex gap-2">
				<Button size="xs" variant="outline" onClick={() => update.mutate({ hidden_types: [] })}>
					Show all
				</Button>
				<Button size="xs" variant="outline" onClick={() => update.mutate({ hidden_types: all })}>
					Hide all
				</Button>
			</div>
			{/* a box of its own (user: the results ended up far below a list of 80+ types) */}
			<div className="max-h-72 overflow-y-auto rounded border p-1">
				{types.data.sections.map((sec) => (
					<div key={sec.title} className="flex flex-col">
						<div className="py-1 text-xs font-semibold text-muted-foreground">{sec.title}</div>
						{sec.rows.map((row) => (
							<div key={row.label} className="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-accent">
								<Checkbox
									checked={!hidden.has(row.label)}
									onCheckedChange={(v) => set(row.label, v === true)}
									aria-label={`Show ${row.label}`}
								/>
								<IconPicture name={row.icon} />
								<button
									type="button"
									className="flex-1 truncate text-left"
									title={row.aliases || row.label}
									onClick={() => onList(row.label, sec.title === "Map icons" ? row.icon : null)}
								>
									{row.label} <span className="text-muted-foreground">({row.count})</span>
								</button>
							</div>
						))}
					</div>
				))}
			</div>
		</div>
	);
}
