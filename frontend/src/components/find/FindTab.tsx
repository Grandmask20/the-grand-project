import { SearchIcon, XIcon } from "lucide-react";
import { useEffect } from "react";
import { Section } from "@/components/common/Section";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useListType } from "@/hooks/find/UseListType";
import { useSearch } from "@/hooks/find/UseSearch";
import { useAppStore } from "@/store/AppStore";
import { ResultList } from "./ResultList";
import { SelectedBox } from "./SelectedBox";
import { TypeList } from "./TypeList";

/** Find: search, the type list (what the map shows), the results and the selected item's details. */
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
		if (listed && list.data) setResults(list.data, `${list.data.length} ${listed.label}`);
	}, [listed, list.data, setResults]);

	const filter = (key: "multi_only" | "only_icon_maps" | "near_only", label: string) => (
		<Label className="font-normal">
			<Checkbox
				checked={!!settings?.[key]}
				onCheckedChange={(v) => update.mutate({ [key]: v === true })}
				aria-label={label}
			/>
			{label}
		</Label>
	);

	return (
		<div className="flex flex-col gap-4">
			<div className="relative">
				<SearchIcon className="absolute top-2 left-2 size-4 text-muted-foreground" />
				<Input
					aria-label="Find"
					placeholder="Find: a name, an icon, #12, or x, y"
					value={text}
					onChange={(e) => setText(e.target.value)}
					onKeyDown={(e) => e.key === "Escape" && clear()}
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
			</div>
			<div className="flex flex-col gap-2">
				{filter("multi_only", "only what 2+ screenshots show")}
				{filter("only_icon_maps", "only maps with a ticked icon")}
				{filter("near_only", "only potential city maps")}
			</div>
			<Section title="Types">
				<TypeList onList={listType} />
			</Section>
			<ResultList />
			<SelectedBox />
		</div>
	);
}
