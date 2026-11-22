import { BookmarkIcon, CheckIcon } from "lucide-react";
import { IconPicture } from "@/components/common/IconPicture";
import { useTypes } from "@/hooks/find/UseTypes";
import { bookmarkLook } from "@/logic/BookmarkLook";
import { isSymbol, SYMBOLS, symbolPath } from "@/logic/Symbols";
import { cn } from "@/utils/Cn";

/** The colours offered for a bookmark or a group (any other: the colour picker beside them). */
export const LOOK_COLOURS = [
	"#c8a45c",
	"#ef4444",
	"#f97316",
	"#facc15",
	"#4ade80",
	"#2dd4bf",
	"#38bdf8",
	"#60a5fa",
	"#a78bfa",
	"#f472b6",
	"#e7e4dc",
];

/** A plain symbol in a colour, edged in black (as the map draws it). */
export function SymbolMark({ icon, colour, size = 16 }: { icon: string; colour: string; size?: number }) {
	return (
		<svg viewBox="0 0 24 24" width={size} height={size} className="shrink-0" aria-hidden="true">
			<path d={symbolPath(icon)} fill={colour} fillRule="evenodd" stroke="rgba(0,0,0,0.85)" strokeWidth={1.5} />
		</svg>
	);
}

/** A bookmark as the list and the map draw it: a symbol in its colour; a picture in a ring of its colour (none:
 * `plain`); else the bookmark sign in its colour. */
export function LookMark({
	colour,
	icon,
	plain = false,
	size = 16,
}: {
	colour: string;
	icon?: string;
	plain?: boolean;
	size?: number;
}) {
	if (icon && isSymbol(icon)) return <SymbolMark icon={icon} colour={colour} size={size + 2} />;
	if (icon)
		return (
			<span
				className="inline-flex shrink-0 items-center justify-center rounded-full"
				style={{ width: size + 4, height: size + 4, boxShadow: plain ? undefined : `0 0 0 2px ${colour}` }}
			>
				<IconPicture name={icon} size={size} />
			</span>
		);
	return <BookmarkIcon className="shrink-0" style={{ color: colour, width: size, height: size }} aria-hidden />;
}

/**
 * A bookmark's or a group's look (user: the pen opens a menu for icons and colours, per group and per bookmark): a
 * colour and an icon, each "" for none, which shows `fallback` (the group's look, or the page's). An icon is a plain
 * symbol in the colour (user: "utf icons", like the game's markers) or a map icon's picture in a ring of the colour.
 * The colour "none" (`plain`, user: an option for no border, as a colour) draws a picture without its ring.
 */
export function LookPicker({
	colour,
	icon,
	plain,
	onColour,
	onIcon,
	onPlain,
	fallback,
}: {
	colour: string;
	icon: string;
	plain: boolean;
	onColour: (c: string) => void;
	onIcon: (i: string) => void;
	onPlain: (p: boolean) => void;
	fallback: { colour: string; icon?: string; plain?: boolean; from: string };
}) {
	const shown = colour || fallback.colour;
	// a colour picked (or the standard one): with its ring again
	const pick = (c: string) => {
		onColour(c);
		onPlain(false);
	};
	const types = useTypes().data;
	// the atlas's map icons and places: the pictures the map has for its icons
	const pictures = (types?.sections ?? []).flatMap((s) =>
		s.rows.filter((r) => r.icon && r.icon !== "Unidentified").map((r) => ({ name: r.icon, label: r.label })),
	);
	const seen = new Set<string>();
	const choices = pictures.filter((p) => !seen.has(p.name) && seen.add(p.name));
	const swatch = (c: string, label: string, on: boolean, onClick: () => void) => (
		<button
			key={label}
			type="button"
			aria-pressed={on}
			aria-label={label}
			title={label}
			onClick={onClick}
			className={cn(
				"flex size-6 items-center justify-center rounded-full border",
				on ? "ring-2 ring-gold ring-offset-1 ring-offset-background" : "hover:ring-1 hover:ring-border",
			)}
			style={{ background: c }}
		>
			{on && <CheckIcon className="size-3.5 text-background" aria-hidden />}
		</button>
	);
	return (
		<div className="flex flex-col gap-3">
			<div className="flex items-center gap-2 text-xs text-muted-foreground">
				{/* (as it will be drawn: the map's rule) */}
				<LookMark {...bookmarkLook({ colour, icon, plain }, fallback)} colour={shown} size={18} />
				as it shows
			</div>
			<div className="flex flex-col gap-1.5">
				<span className="text-xs font-medium">Colour</span>
				<div className="flex flex-wrap items-center gap-1.5" title="Colour">
					<button
						type="button"
						aria-pressed={!colour && !plain}
						title={`None: ${fallback.from}`}
						aria-label={`No colour of its own (${fallback.from})`}
						onClick={() => pick("")}
						className={cn(
							"h-6 rounded-full border px-2 text-xs",
							!colour && !plain ? "border-gold text-foreground" : "text-muted-foreground hover:text-foreground",
						)}
					>
						{fallback.from}
					</button>
					{LOOK_COLOURS.map((c) => swatch(c, c, colour === c && !plain, () => pick(c)))}
					<label
						className="flex h-6 cursor-pointer items-center gap-1 rounded-full border px-1.5 text-xs text-muted-foreground hover:text-foreground"
						title="Any other colour"
					>
						<input
							type="color"
							value={colour || fallback.colour}
							onChange={(e) => pick(e.target.value)}
							aria-label="Any other colour"
							className="size-4 cursor-pointer rounded-full border-0 bg-transparent p-0"
						/>
						other
					</label>
					{/* no colour: a picture without its ring, a symbol and the name in the standard colour */}
					<button
						type="button"
						aria-pressed={plain}
						aria-label="No colour"
						title="None: an icon without its coloured ring"
						onClick={() => {
							onColour("");
							onPlain(true);
						}}
						className={cn(
							"h-6 rounded-full border px-2 text-xs",
							plain ? "border-gold text-foreground" : "text-muted-foreground hover:text-foreground",
						)}
					>
						none
					</button>
				</div>
			</div>
			<div className="flex flex-col gap-1.5">
				<span className="text-xs font-medium">Icon</span>
				<div
					className="grid max-h-36 grid-cols-[repeat(auto-fill,minmax(2rem,1fr))] gap-1 overflow-y-auto rounded border p-1"
					title="Icon"
				>
					<button
						type="button"
						aria-pressed={!icon}
						aria-label="No icon"
						title={`None: ${fallback.icon ? fallback.from : "the bookmark sign"}`}
						onClick={() => onIcon("")}
						className={cn(
							"flex h-8 items-center justify-center rounded text-xs",
							!icon ? "bg-accent ring-1 ring-gold" : "text-muted-foreground hover:bg-accent",
						)}
					>
						none
					</button>
					{Object.keys(SYMBOLS).map((name) => (
						<button
							key={name}
							type="button"
							aria-pressed={icon === `sym:${name}`}
							aria-label={name}
							title={name}
							onClick={() => onIcon(`sym:${name}`)}
							className={cn(
								"flex h-8 items-center justify-center rounded",
								icon === `sym:${name}` ? "bg-accent ring-1 ring-gold" : "hover:bg-accent",
							)}
						>
							<SymbolMark icon={`sym:${name}`} colour={shown} size={20} />
						</button>
					))}
					{choices.map((p) => (
						<button
							key={p.name}
							type="button"
							aria-pressed={icon === p.name}
							aria-label={p.label}
							title={p.label}
							onClick={() => onIcon(p.name)}
							className={cn(
								"flex h-8 items-center justify-center rounded",
								icon === p.name ? "bg-accent ring-1 ring-gold" : "hover:bg-accent",
							)}
						>
							<IconPicture name={p.name} size={22} />
						</button>
					))}
				</div>
			</div>
		</div>
	);
}
