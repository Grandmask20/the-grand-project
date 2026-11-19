import type { ReactNode } from "react";
import { PagePicker } from "@/components/common/PagePicker";
import { useAppStore } from "@/store/AppStore";

/** A side panel tab with pages picked by a row of buttons (user: fewer tabs, the rest as pages inside, like the View
 * tab's two pages). The page shown is kept per tab in the store, so asking for an old tab's id ("auto", "route",
 * "debug") opens its tab on that page. */
export function PagedTab({ tab, label, pages }: { tab: string; label: string; pages: [string, string, ReactNode][] }) {
	const asked = useAppStore((s) => s.pages[tab]);
	const setPage = useAppStore((s) => s.setPage);
	const page = pages.find(([k]) => k === asked) ?? pages[0];
	if (!page) return null;
	return (
		<div className="flex h-full flex-col gap-3">
			{pages.length > 1 && (
				<PagePicker
					label={label}
					pages={pages.map(([k, text]) => [k, text] as [string, string])}
					value={page[0]}
					onChange={(k) => setPage(tab, k)}
				/>
			)}
			<div className="min-h-0 flex-1">{page[2]}</div>
		</div>
	);
}
