import { SearchIcon, XIcon } from "lucide-react";
import { useEffect, useRef } from "react";
import { Pill } from "@/components/common/Pill";
import { Section } from "@/components/common/Section";
import { Input } from "@/components/ui/input";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useListType } from "@/hooks/find/UseListType";
import { useSearch } from "@/hooks/find/UseSearch";
import { useAppStore } from "@/store/AppStore";
import { ResultList } from "./ResultList";
import { TypeList } from "./TypeList";

/** Find: search with its results dropping down under it, the filters' pills and the type list (what the map shows).
 * What is selected shows in the window over the map. */
export function FindTab() {
	// Find's state lives in the store (one owner: the map's Esc clears it too, and it outlasts this tab: CodeRabbit)
	const text = useAppStore((s) => s.findText);
	const setText = useAppStore((s) => s.setFindText);
	const query = useAppStore((s) => s.query);
	const setQuery = useAppStore((s) => s.setQuery);
	const listed = useAppStore((s) => s.listed);
	const listType = useAppStore((s) => s.listType);
	const clear = useAppStore((s) => s.clearFind);
	const setResults = useAppStore((s) => s.setResults);
	const flyTo = useAppStore((s) => s.flyTo);
	const setGoto = useAppStore((s) => s.setGoto);
	const search = useSearch(query);
	const list = useListType(listed?.label ?? null);
	const settings = useSettings();
	const update = useUpdateSettings();

	// typing settles for a moment before searching
	useEffect(() => {
		if (text === useAppStore.getState().query) return;
		const t = setTimeout(() => setQuery(text), 250);
		return () => clearTimeout(t);
	}, [text, setQuery]);

	useEffect(() => {
		const d = search.data;
		if (!query.trim()) {
			if (!listed) setResults([], "");
			return;
		}
		if (!d) return;
		if ("goto" in d) {
			const [x, y] = d.goto;
			setGoto([x, y]);
			flyTo(x, y, 1);
			setResults([], `centred on ${x.toFixed(0)}, ${y.toFixed(0)} (marked)`);
		} else setResults(d.results, `${d.results.length} match(es) for "${query.trim()}"`);
	}, [search.data, query, listed, setResults, setGoto, flyTo]);

	useEffect(() => {
		// only while no search is typed (a late listing replaced its results: CodeRabbit)
		if (listed && !query.trim() && list.data) setResults(list.data, `${list.data.length} ${listed.label}`);
	}, [listed, list.data, query, setResults]);

	// the results drop down under the search when a list comes (a search, a type clicked) and stay while you go through
	// them (user: a pick or a click on the map closed them); their ✕ or Esc closes them, the search's focus or ↓ opens
	// them again
	const resultsTitle = useAppStore((s) => s.resultsTitle);
	const open = useAppStore((s) => s.resultsOpen);
	const setOpen = useAppStore((s) => s.setResultsOpen);
	const searchBox = useRef<HTMLDivElement>(null);
	useEffect(() => {
		if (!open) return;
		const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
		window.addEventListener("keydown", esc);
		return () => window.removeEventListener("keydown", esc);
	}, [open, setOpen]);
	const down = () => {
		setOpen(true);
		// the list is drawn by now when it was open; else on the next frame
		requestAnimationFrame(() => searchBox.current?.querySelector<HTMLButtonElement>("ul button")?.focus());
	};

	const kinds = useAppStore((s) => s.findKinds);
	const toggleKind = useAppStore((s) => s.toggleFindKind);
	// the filters as pills under the search (PO's canvas): the kinds of results, then what the map shows; a setting's
	// pill has its whole sentence as its name
	const filter = (key: "multi_only" | "only_icon_maps" | "near_only", short: string, label: string) => (
		<Pill on={!!settings?.[key]} label={label} onClick={() => update.mutate({ [key]: !settings?.[key] })}>
			{short}
		</Pill>
	);

	return (
		<div className="flex flex-col gap-4">
			<div ref={searchBox} className="relative">
				<SearchIcon className="absolute top-2 left-2 size-4 text-muted-foreground" />
				<Input
					aria-label="Find"
					placeholder="Find: a name, an icon, #12, or x, y"
					value={text}
					onChange={(e) => setText(e.target.value)}
					onFocus={() => resultsTitle && setOpen(true)}
					onKeyDown={(e) => {
						if (e.key === "Escape") clear();
						else if (e.key === "ArrowDown") {
							e.preventDefault();
							down();
						}
					}}
					className="pr-8 pl-8"
				/>
				<button
					type="button"
					aria-label="Clear the search"
					title="Clear the search and the rings on the map (Esc)"
					onClick={clear}
					className="absolute top-1.5 right-1.5 rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
				>
					<XIcon className="size-4" />
				</button>
				{open && <ResultList onClose={() => setOpen(false)} />}
			</div>
			<div className="flex flex-wrap gap-1.5">
				{(
					[
						["node", "Maps"],
						["icon", "Icons"],
						["landmark", "Places"],
						["bookmark", "Bookmarks"],
					] as const
				).map(([kind, name]) => (
					<Pill key={kind} on={kinds.includes(kind)} title={`${name} in the results`} onClick={() => toggleKind(kind)}>
						{name}
					</Pill>
				))}
			</div>
			<div className="flex flex-wrap items-center gap-1.5">
				<span className="mr-1 text-xs text-muted-foreground">Only</span>
				{filter("multi_only", "2+ screenshots", "only what 2+ screenshots show")}
				{filter("only_icon_maps", "ticked icons only", "only maps with a ticked icon")}
				{filter("near_only", "potential cities", "only potential city maps")}
			</div>
			<Section title="Types">
				<TypeList onList={listType} />
			</Section>
		</div>
	);
}
