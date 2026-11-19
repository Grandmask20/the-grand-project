import { useEffect, useRef, useState } from "react";
import { Slider } from "@/components/ui/slider";

/** A slider for one setting: it moves freely while dragged and saves once, when let go.
 *
 * Saving on every step sent one change per step (user: the "drawn by at least" slider lagged; each step remade every
 * map tile and the 3D scene in the app). `onPreview` shows a look on the page while dragging, without saving.
 */
export function SettingSlider({
	label,
	value,
	min,
	max,
	step,
	onCommit,
	onPreview,
	format,
	className = "w-36",
	valueWidth = "w-12",
}: {
	label: string;
	value: number;
	min: number;
	max: number;
	step: number;
	onCommit: (v: number) => void;
	onPreview?: (v: number) => void;
	format?: (v: number) => string;
	className?: string;
	valueWidth?: string;
}) {
	const [draft, setDraft] = useState<number | null>(null);
	// a pointer drag going on: the saved value when it began (its preview changes `value` on the page meanwhile), else
	// null. Only drags are tracked: arrow keys save each step at once (Radix commits a key step before it reports the
	// change, which left a stale start that skipped a later save: CodeRabbit)
	const start = useRef<number | null>(null);
	const shown = draft ?? value;
	// gone in the middle of a drag (the tab switched): its preview is taken back, as nothing was saved
	const undo = useRef(onPreview);
	undo.current = onPreview;
	useEffect(
		() => () => {
			if (start.current !== null) undo.current?.(start.current);
		},
		[],
	);
	return (
		<>
			<Slider
				min={min}
				max={max}
				step={step}
				value={[shown]}
				onPointerDown={() => {
					start.current = value;
				}}
				onValueChange={([v]) => {
					if (start.current === null) return; // a key step: saved by its commit
					setDraft(v);
					onPreview?.(v);
				}}
				onValueCommit={([v]) => {
					const from = start.current ?? value;
					start.current = null;
					setDraft(null);
					if (v !== from) onCommit(v);
				}}
				className={className}
				aria-label={label}
			/>
			{format && <span className={`${valueWidth} text-xs`}>{format(shown)}</span>}
		</>
	);
}
