import { type ReactNode, useId } from "react";
import { PagePicker, pageIds } from "@/components/common/PagePicker";
import { useAppStore } from "@/store/AppStore";

/** A side panel tab with pages picked by a row of buttons (user: fewer tabs, the rest as pages inside, like the View
 * tab's two pages). The page shown is kept per tab in the store, so asking for an old tab's id ("auto", "route",
 * "debug") opens its tab on that page. */
export function PagedTab({ tab, label, pages }: { tab: string; label: string; pages: [string, string, ReactNode][] }) {
	const asked = useAppStore((s) => s.pages[tab]);
	const setPage = useAppStore((s) => s.setPage);
	const page = pages.find(([k]) => k === asked) ?? pages[0];
	const idBase = useId();
	if (!page) return null;
	const ids = pageIds(idBase, page[0]);
	return (
		<div className="flex h-full flex-col gap-3">
			{pages.length > 1 && (
				<PagePicker
					label={label}
					pages={pages.map(([k, text]) => [k, text] as [string, string])}
					value={page[0]}
					onChange={(k) => setPage(tab, k)}
					idBase={idBase}
				/>
			)}
			{/* only the page body starts again on another page: the picker stays, with the focus on it (CodeRabbit) */}
			<div
				key={page[0]}
				className="min-h-0 flex-1"
				{...(pages.length > 1 ? { id: ids.panel, role: "tabpanel", "aria-labelledby": ids.tab } : {})}
			>
				{page[2]}
			</div>
		</div>
	);
}
