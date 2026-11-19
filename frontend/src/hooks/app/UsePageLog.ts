import { useEffect } from "react";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { type AppStoreState, useAppStore } from "@/store/AppStore";

/** What changed on the page between two store states, as log lines (tabs, modes, selections, dialogs, errors). */
export function pageChanges(s: AppStoreState, before: AppStoreState): string[] {
	const out: string[] = [];
	if (s.tab !== before.tab) out.push(`tab ${s.tab}`);
	if (s.mode.kind !== before.mode.kind) out.push(`mode ${s.mode.kind}`);
	const sel = s.selected;
	const was = before.selected;
	if (sel?.kind !== was?.kind || sel?.id !== was?.id)
		out.push(sel ? `selected ${sel.kind} ${sel.id}: ${sel.title}` : "selection cleared");
	if (s.bookmarkEdit && !before.bookmarkEdit)
		out.push(`bookmark dialog: ${s.bookmarkEdit.id === null ? "new" : `bookmark ${s.bookmarkEdit.id}`}`);
	if (s.prompt && !before.prompt) out.push(`asked: ${s.prompt.title}`);
	if (s.confirm && !before.confirm) out.push(`confirm: ${s.confirm.title}`);
	if (s.error && s.error !== before.error) out.push(`error shown: ${s.error}`);
	return out;
}

/** Tell the app what is done on the page, for its log file (user: "logs are still not heavily detailed enough": the
 * page's own steps never reached it). Lines are sent together, a moment after they happen. */
export function usePageLog() {
	const app = useAppClient();
	useEffect(() => {
		let lines: string[] = [];
		let timer: ReturnType<typeof setTimeout> | null = null;
		const unsubscribe = useAppStore.subscribe((s, before) => {
			const more = pageChanges(s, before);
			if (!more.length) return;
			lines.push(...more);
			timer ??= setTimeout(() => {
				const send = lines;
				lines = [];
				timer = null;
				app.log(send).catch(() => {}); // (a log line never bothers you with an error)
			}, 300);
		});
		return () => {
			unsubscribe();
			if (timer) clearTimeout(timer);
		};
	}, [app]);
}
