import { type KeyboardEvent, useRef } from "react";
import { Button } from "@/components/ui/button";

/** The ids that tie a page picker's buttons to the page they show (`base`: from useId). */
export const pageIds = (base: string, page: string) => ({ tab: `${base}-tab-${page}`, panel: `${base}-panel` });

/** A tab's pages as a row of buttons (the View tab's Map settings / 3D view settings; the Atlases tab's Atlases /
 * Auto-add; Bookmarks / Route; Log / Debug: user's side panel, fewer tabs with pages inside). Tabs as the WAI pattern
 * has them (CodeRabbit): one stop for Tab, the arrow keys / Home / End move and pick, each tied to the page shown
 * (`idBase`: the page is `pageIds(idBase, page).panel`). */
export function PagePicker<K extends string>({
	label,
	pages,
	value,
	onChange,
	idBase,
}: {
	label: string;
	pages: [K, string][];
	value: K;
	onChange: (page: K) => void;
	idBase: string;
}) {
	const buttons = useRef(new Map<K, HTMLButtonElement>());
	const keys = (e: KeyboardEvent<HTMLDivElement>) => {
		const at = pages.findIndex(([k]) => k === value);
		const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: pages.length - 1 }[e.key];
		if (to === undefined) return;
		e.preventDefault();
		const [k] = pages[(to + pages.length) % pages.length];
		onChange(k);
		buttons.current.get(k)?.focus();
	};
	return (
		<div className="flex gap-1.5" role="tablist" aria-label={label} onKeyDown={keys}>
			{pages.map(([k, text]) => (
				<Button
					key={k}
					ref={(b) => {
						if (b) buttons.current.set(k, b);
						else buttons.current.delete(k);
					}}
					id={pageIds(idBase, k).tab}
					size="xs"
					role="tab"
					aria-selected={value === k}
					aria-controls={pageIds(idBase, k).panel}
					tabIndex={value === k ? 0 : -1}
					variant={value === k ? "default" : "outline"}
					onClick={() => onChange(k)}
				>
					{text}
				</Button>
			))}
		</div>
	);
}
