import type { ComponentProps, FocusEvent, ReactNode } from "react";
import { Section } from "@/components/common/Section";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { DetectionSettings } from "@/domain/app/UiSettings";
import { useMeta } from "@/hooks/app/UseMeta";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";

/** Settings still being tried out: the detector (the classical one or the RF-DETR model) and how many screenshots it
 * detects at once. Saved at once, used from the app's next start (the app picks its detector as it starts). */
export function ExperimentalTab() {
	const saved = useSettings()?.detection;
	const choices = useMeta().data?.detection;
	const update = useUpdateSettings();
	if (!saved || !choices) return null;
	const set = (change: Partial<DetectionSettings>) => update.mutate({ detection: change });
	const missing = choices.rf_detr_missing;
	const keys = Object.keys(choices.active) as (keyof DetectionSettings)[];
	const waiting = keys.some((k) => saved[k] !== choices.active[k]);
	const workers = (text: string) => {
		const n = Math.round(Number(text));
		return text && Number.isFinite(n) ? String(Math.min(choices.max_workers, Math.max(1, n))) : null;
	};

	return (
		<div className="flex flex-col gap-4">
			<p className="text-xs text-muted-foreground">
				Settings still being tried out. Changes are saved at once and used from the app's next start.
			</p>
			{waiting && (
				<p role="status" className="text-xs text-gold">
					Saved: restart the app to apply.
				</p>
			)}
			<Section title="Classical detection">
				<Row label="Max workers">
					<CommitInput
						type="number"
						min={1}
						max={choices.max_workers}
						className="w-20"
						aria-label="Max workers"
						value={String(saved.workers)}
						parse={workers}
						onCommit={(v) => set({ workers: Number(v) })}
					/>
				</Row>
				<p className="text-xs text-muted-foreground">
					Screenshots detected at once, at most {choices.max_workers} on this computer. With RF-DETR on, each worker
					loads its own copy of the model.
				</p>
			</Section>
			<Section title="RF-DETR detection">
				<Label className="font-normal">
					<Switch
						checked={saved.rf_detr}
						disabled={!!missing && !saved.rf_detr}
						onCheckedChange={(on) => set({ rf_detr: on === true })}
						aria-label="RF-DETR detection"
					/>
					Detect with the RF-DETR model
				</Label>
				{missing && (
					<p className="text-xs text-muted-foreground">
						Needs {missing}, which this copy of the program doesn't have (a developer install does).
					</p>
				)}
				<Row label="Model">
					<CommitInput
						aria-label="RF-DETR model"
						placeholder={choices.default_model}
						title="A model folder, or a Hugging Face id owner/name[@revision] (empty: the default one)"
						value={saved.model}
						onCommit={(v) => set({ model: v })}
					/>
				</Row>
				<Row label="Device">
					<Select value={saved.device} onValueChange={(v) => set({ device: v })}>
						<SelectTrigger size="sm" className="min-w-36" aria-label="RF-DETR device">
							<SelectValue />
						</SelectTrigger>
						<SelectContent>
							{choices.devices.map((d) => (
								<SelectItem key={d} value={d}>
									{d}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
				</Row>
				<p className="text-xs text-muted-foreground">
					The model is a folder or a Hugging Face id (owner/name[@revision], downloaded once); auto picks CUDA, then
					Apple's MPS, then the CPU.
				</p>
			</Section>
		</div>
	);
}

/** A setting's name and its control, as the View tab lays them out. */
function Row({ label, children }: { label: string; children: ReactNode }) {
	return (
		<div className="flex items-center gap-2">
			<span className="w-24 shrink-0 text-xs text-muted-foreground">{label}</span>
			{children}
		</div>
	);
}

/** A text box saved when it is left or Enter is pressed, not at each key. `parse` turns its text into the value to
 * save (null: not one, the saved value comes back). */
function CommitInput({
	value,
	onCommit,
	parse = (text) => text,
	...props
}: Omit<ComponentProps<typeof Input>, "value" | "defaultValue" | "onBlur"> & {
	value: string;
	onCommit: (value: string) => void;
	parse?: (text: string) => string | null;
}) {
	const commit = (e: FocusEvent<HTMLInputElement>) => {
		const next = parse(e.currentTarget.value.trim());
		if (next === null || next === value) e.currentTarget.value = value;
		else onCommit(next);
	};
	return (
		<Input
			key={value}
			defaultValue={value}
			onBlur={commit}
			onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
			{...props}
		/>
	);
}
