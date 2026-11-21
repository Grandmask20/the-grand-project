import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ChoiceGroup, ChoiceItem, Question } from "@/domain/app/Question";
import { useAppStore } from "@/store/AppStore";
import { cn } from "@/utils/Cn";

/** A question with groups to tick: a Re-check's changes (user: "it should prompt you what changed in groups, and you
 * can tick which things to update", laid out after the user's mockup: a wide box over the top of the map, a row of
 * small cards (name, +added / −removed, Keep?) and Apply at the right). A click on a card lists its changes above
 * the row; a click on one of those shows its spot on the map. Answered only by Apply: what is unticked stays. */
export function ChoicesDialog({ q, onAnswer }: { q: Question; onAnswer: (picked: string[]) => void }) {
	const groups = q.choices?.groups ?? [];
	const [ticked, setTicked] = useState<Record<string, boolean>>(() =>
		Object.fromEntries(groups.map((g) => [g.id, g.ticked && g.count > 0])),
	);
	const [shown, setShown] = useState<string | null>(() => groups.find((g) => g.count > 0)?.id ?? null);
	const flyTo = useAppStore((s) => s.flyTo);
	const setGoto = useAppStore((s) => s.setGoto);
	const open = groups.find((g) => g.id === shown) ?? null;
	const box = useRef<HTMLDivElement>(null);
	// a change's spot goes below the box, not under it, marked with Find's cross (a map it adds isn't drawn yet)
	const go = (it: ChoiceItem) => {
		setGoto([it.x, it.y]);
		flyTo(it.x, it.y, 0.6, box.current?.getBoundingClientRect().bottom);
	};
	const apply = () => {
		setGoto(null);
		onAnswer(groups.filter((g) => ticked[g.id]).map((g) => g.id));
	};

	return (
		<Dialog open modal={false}>
			<DialogContent
				ref={box}
				overlay={false}
				showCloseButton={false}
				onEscapeKeyDown={(e) => e.preventDefault()}
				onInteractOutside={(e) => e.preventDefault()}
				className="top-12 max-h-[calc(100vh-4rem)] translate-y-0 grid-rows-[auto_1fr_auto] sm:max-w-4xl"
			>
				<DialogHeader>
					<DialogTitle className="font-bold text-2xl uppercase tracking-wide">
						{q.labels?.title ?? "Choose"}
					</DialogTitle>
					<DialogDescription className="text-base text-foreground">{q.question}</DialogDescription>
				</DialogHeader>
				<ChangeList group={open} onGo={go} />
				<div className="flex flex-wrap items-end gap-2">
					{groups.map((g) => (
						<GroupCard
							key={g.id}
							g={g}
							ticked={!!ticked[g.id]}
							onTick={(v) => setTicked((t) => ({ ...t, [g.id]: v }))}
							selected={shown === g.id}
							onSelect={() => setShown(g.id)}
						/>
					))}
					<Button
						autoFocus
						className="ml-auto h-11 bg-emerald-600 px-8 font-bold text-lg text-white uppercase hover:bg-emerald-500"
						onClick={apply}
					>
						{q.labels?.yes ?? "Apply"}
					</Button>
				</div>
			</DialogContent>
		</Dialog>
	);
}

const KIND_MARK: Record<string, { mark: string; cls: string }> = {
	added: { mark: "+", cls: "text-emerald-500" },
	removed: { mark: "−", cls: "text-red-500" },
	change: { mark: "~", cls: "text-amber-500" },
};

/** The open card's changes, each named, marked +/−/~ and placed (a click shows it on the map). */
function ChangeList({ group, onGo }: { group: ChoiceGroup | null; onGo: (it: ChoiceItem) => void }) {
	if (!group || group.count === 0) {
		return (
			<p className="min-h-24 text-muted-foreground text-sm">
				{group ? `${group.name}: no changes.` : "Nothing changed."}
			</p>
		);
	}
	return (
		<div className="min-h-24 overflow-hidden rounded border">
			<p className="border-b bg-muted/40 px-2 py-1 font-medium text-sm">
				{group.name}: what changed <span className="text-muted-foreground">(click one to see it on the map)</span>
			</p>
			<ul className="max-h-52 overflow-y-auto py-1 text-sm">
				{group.items.map((it, k) => {
					const m = KIND_MARK[it.kind ?? "change"] ?? KIND_MARK.change;
					return (
						// biome-ignore lint/suspicious/noArrayIndexKey: a fixed list (two changes can read alike)
						<li key={k}>
							<button
								type="button"
								className="flex w-full gap-2 px-2 text-left hover:bg-accent"
								title="Show it on the map"
								onClick={() => onGo(it)}
							>
								<span className={cn("w-3 font-bold", m.cls)}>{m.mark}</span>
								<span>{it.text}</span>
								<span className="ml-auto text-muted-foreground">
									{Math.round(it.x)}, {Math.round(it.y)}
								</span>
							</button>
						</li>
					);
				})}
				{group.count > group.items.length && (
					<li className="px-2 text-muted-foreground">…and {group.count - group.items.length} more</li>
				)}
			</ul>
		</div>
	);
}

/** One group: its name, +added / −removed (~changed), and Keep? (ticked: its changes are taken). */
function GroupCard({
	g,
	ticked,
	onTick,
	selected,
	onSelect,
}: {
	g: ChoiceGroup;
	ticked: boolean;
	onTick: (v: boolean) => void;
	selected: boolean;
	onSelect: () => void;
}) {
	const none = g.count === 0;
	const id = `choice-${g.id}`;
	return (
		<div
			className={cn(
				"flex min-w-32 flex-col gap-0.5 rounded border bg-muted/30 px-2 py-1.5",
				selected && "border-primary",
				none && "opacity-50",
			)}
		>
			<div className="flex items-center gap-2">
				<button
					type="button"
					className="font-bold text-sm uppercase hover:underline"
					aria-pressed={selected}
					aria-label={`Show what changed in ${g.name}`}
					onClick={onSelect}
				>
					{g.name}
				</button>
				<label htmlFor={id} className="ml-auto text-muted-foreground text-xs uppercase">
					Keep?
				</label>
				<Checkbox
					id={id}
					aria-label={g.name}
					checked={ticked}
					disabled={none}
					onCheckedChange={(v) => onTick(v === true)}
				/>
			</div>
			<button type="button" className="flex gap-2 text-left font-semibold text-sm" onClick={onSelect} tabIndex={-1}>
				{none ? (
					<span className="font-normal text-muted-foreground">no changes</span>
				) : (
					<>
						<span className="text-emerald-500">+{g.added}</span>
						<span className="text-red-500">−{g.removed}</span>
						{g.changed > 0 && <span className="text-amber-500">~{g.changed}</span>}
					</>
				)}
			</button>
			{!none && !ticked && <span className="text-muted-foreground text-xs">stays as before</span>}
		</div>
	);
}
