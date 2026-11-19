import { Button } from "@/components/ui/button";

/** A tab's pages as a row of buttons (the View tab's Map settings / 3D view settings; the Atlases tab's Atlases /
 * Auto-add; Bookmarks / Route; Log / Debug: user's side panel, fewer tabs with pages inside). */
export function PagePicker<K extends string>({
	label,
	pages,
	value,
	onChange,
}: {
	label: string;
	pages: [K, string][];
	value: K;
	onChange: (page: K) => void;
}) {
	return (
		<div className="flex gap-1.5" role="tablist" aria-label={label}>
			{pages.map(([k, text]) => (
				<Button
					key={k}
					size="xs"
					role="tab"
					aria-selected={value === k}
					variant={value === k ? "default" : "outline"}
					onClick={() => onChange(k)}
				>
					{text}
				</Button>
			))}
		</div>
	);
}
