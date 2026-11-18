/** A colour square that opens the browser's colour picker. */
export function ColourSwatch({ label, value, onChange }: { label: string; value: string; onChange: (hex: string) => void }) {
	return (
		<label className="flex cursor-pointer items-center gap-2 text-xs">
			<input
				type="color"
				value={value}
				onChange={(e) => onChange(e.target.value)}
				aria-label={label}
				className="h-6 w-8 cursor-pointer rounded border bg-transparent p-0"
			/>
			{label}
		</label>
	);
}
