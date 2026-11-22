import { ChevronDownIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";

interface Props {
	id?: string;
	value: string;
	onChange: (value: string) => void;
	options: string[];
	placeholder?: string;
}

/**
 * A text box with a dropdown of choices, like the old window's combobox (user: the bookmark group was a plain
 * text box): pick one from the list, or type a new one. Typing narrows the list.
 */
export function ComboInput({ id, value, onChange, options, placeholder }: Props) {
	const [open, setOpen] = useState(false);
	const [typed, setTyped] = useState(false);
	const box = useRef<HTMLDivElement>(null);

	useEffect(() => {
		if (!open) return;
		const away = (e: PointerEvent) => {
			if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
		};
		document.addEventListener("pointerdown", away);
		return () => document.removeEventListener("pointerdown", away);
	}, [open]);

	const q = value.trim().toLowerCase();
	const shown = typed && q ? options.filter((o) => o.toLowerCase().includes(q)) : options;

	return (
		<div ref={box} className="relative">
			<Input
				id={id}
				value={value}
				placeholder={placeholder}
				autoComplete="off"
				onChange={(e) => {
					onChange(e.target.value);
					setTyped(true);
					setOpen(true);
				}}
				onKeyDown={(e) => {
					if (e.key === "ArrowDown") {
						setTyped(false);
						setOpen(true);
					} else if (e.key === "Escape" && open) {
						e.stopPropagation();
						setOpen(false);
					}
				}}
				className="pr-8"
			/>
			<button
				type="button"
				aria-label="Show the choices"
				onClick={() => {
					setTyped(false);
					setOpen(!open);
				}}
				className="absolute top-1.5 right-1.5 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
			>
				<ChevronDownIcon className="size-4" />
			</button>
			{open && shown.length > 0 && (
				<ul className="absolute z-50 mt-1 max-h-56 w-full overflow-y-auto poe-panel poe-panel-sm py-1 shadow-lg">
					{shown.map((o) => (
						<li key={o}>
							<button
								type="button"
								className={`w-full truncate px-2.5 py-1 text-left text-sm hover:bg-accent ${o === value ? "text-gold" : ""}`}
								onClick={() => {
									onChange(o);
									setOpen(false);
								}}
							>
								{o}
							</button>
						</li>
					))}
				</ul>
			)}
		</div>
	);
}
