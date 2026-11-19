import { useEffect } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import type { MapMode } from "@/store/AppStore";
import { type AppStoreState, useAppStore } from "@/store/AppStore";

// the side panel's tabs as you see them
const TABS: Record<string, string> = {
	find: "Find",
	view: "View",
	auto: "Auto-add",
	bookmarks: "Bookmarks",
	atlases: "Saved atlases",
	route: "Route",
	log: "Log",
	debug: "Debug",
};

// a map mode starting, in plain words (its end says "... ended")
const MODES: Record<MapMode["kind"], string> = {
	normal: "",
	lasso: "Biome select",
	bookmark: "Add bookmark",
	player: "I'm here (click your map)",
	ghost: "Placing a screenshot by hand",
	"debug-link": "Debug: missing path (click the second map)",
	route: "Route (click two maps)",
};

/** What you did on the page between two store states, as log lines anyone can read ("Opened the Bookmarks tab",
 * "Biome select started", "Selected Map #12: Breach"): no ids or app names (user: the log has to make sense to
 * players, not only to developers). */
export function pageChanges(s: AppStoreState, before: AppStoreState): string[] {
	const out: string[] = [];
	if (s.tab !== before.tab) out.push(`Opened the ${TABS[s.tab] ?? s.tab} tab`);
	if (s.mode.kind !== before.mode.kind) {
		if (before.mode.kind !== "normal") out.push(`${MODES[before.mode.kind]} ended`);
		if (s.mode.kind !== "normal") out.push(`${MODES[s.mode.kind]} started`);
	}
	const sel = s.selected;
	const was = before.selected;
	if (sel?.kind !== was?.kind || sel?.id !== was?.id) out.push(sel ? `Selected ${sel.title}` : "Selection cleared");
	if (s.bookmarkEdit && !before.bookmarkEdit)
		out.push(s.bookmarkEdit.id === null ? "New bookmark: dialog opened" : `Editing bookmark "${s.bookmarkEdit.name}"`);
	if (s.prompt && !before.prompt) out.push(`${s.prompt.title}: dialog opened`);
	if (s.filePick && !before.filePick) out.push(`${s.filePick.title}: dialog opened`);
	if (s.confirm && !before.confirm) out.push(`Asked: ${s.confirm.text}`);
	if (s.error && s.error !== before.error) out.push(`Error shown: ${s.error}`);
	return out;
}

/** Tell the app what you do on the page, for the Log tab and the log file (user: "every user made change should be
 * listed"). Sent at once, so the lines keep their order with the app's own (a biome drawn after its selection). */
export function usePageLog() {
	const app = useAppClient();
	useEffect(() => {
		// one request after another: sent side by side, two could be logged the wrong way round
		let queue: Promise<unknown> = Promise.resolve();
		return useAppStore.subscribe((s, before) => {
			const lines = pageChanges(s, before);
			if (!lines.length) return;
			queue = queue.then(() => app.log(lines)).catch(() => {}); // (a log line never bothers you with an error)
		});
	}, [app]);
}
