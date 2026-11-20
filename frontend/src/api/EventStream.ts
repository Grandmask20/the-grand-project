import type { QueryClient } from "@tanstack/react-query";
import type { AppState } from "@/domain/app/AppState";
import type { Question } from "@/domain/app/Question";
import type { UpdateStatus } from "@/domain/app/Update";
import { useAppStore } from "@/store/AppStore";
import { AppQueryKeys } from "./AppQueryKeys";

/** Events from the app (GET /api/events) and what each one refreshes. */
export const EVENT_KINDS = [
	"log",
	"progress",
	"status",
	"model",
	"terrain",
	"filters",
	"atlas",
	"atlases",
	"lists",
	"busy",
	"watch",
	"seams",
	"question",
	"answered",
	"bookmarks",
	"debug",
	"show_tab",
	"update",
] as const;

export type EventKind = (typeof EVENT_KINDS)[number];

const LOG_KEEP = 2000;

/** Keep an update status unless the page has a newer one (its number, "seq", goes up with each change: a button's
 * answer could land after the event of what followed it, CodeRabbit). */
export function keepUpdate(queryClient: QueryClient, r: UpdateStatus): void {
	queryClient.setQueryData<UpdateStatus>(AppQueryKeys.update, (old) => (old && old.seq > r.seq ? old : r));
}

/** Applies one event: small ones patch the cached state, the rest refetch what they change (batched). */
export function createEventHandler(queryClient: QueryClient) {
	let pending = new Set<string>();
	let timer: ReturnType<typeof setTimeout> | null = null;

	const refresh = (...keys: string[]) => {
		for (const k of keys) pending.add(k);
		if (timer) return;
		timer = setTimeout(() => {
			timer = null;
			const keys = pending;
			pending = new Set();
			for (const k of keys) void queryClient.invalidateQueries({ queryKey: [k] });
		}, 120);
	};

	const patch = (fn: (s: AppState) => AppState) =>
		queryClient.setQueryData<AppState>(AppQueryKeys.state, (s) => (s ? fn(s) : s));

	return (kind: EventKind, data: unknown) => {
		switch (kind) {
			case "log":
				// one log per atlas: a line of another atlas's log (work finishing after a switch) is left out
				patch((s) => {
					const d = data as { scope?: string; line?: string } | string;
					if (typeof d === "object" && d && d.scope !== undefined && d.scope !== s.log_scope) return s;
					const line = typeof d === "object" && d ? String(d.line ?? "") : String(d);
					return { ...s, log: [...s.log, line].slice(-LOG_KEEP) };
				});
				break;
			case "progress":
				patch((s) => ({ ...s, progress: (data as string | null) ?? null }));
				break;
			case "status":
				patch((s) => ({ ...s, status: String(data ?? "") }));
				break;
			case "question":
				// an older snapshot on its way lacks it: dropped, and the state asked for again once patched (also when
				// the first load was the one cancelled, with nothing to patch yet: CodeRabbit)
				void queryClient.cancelQueries({ queryKey: AppQueryKeys.state }).then(() => refresh("state"));
				patch((s) => ({
					...s,
					questions: [...s.questions.filter((q) => q.id !== (data as Question).id), data as Question],
				}));
				break;
			case "answered":
				patch((s) => ({ ...s, questions: s.questions.filter((q) => q.id !== (data as { id: number }).id) }));
				break;
			case "model":
			case "atlas":
				refresh(
					"state",
					"parts",
					"types",
					"search",
					"list",
					"info",
					"graph",
					"frames",
					"heat",
					"bookmarks",
					"recent",
					"atlases",
				);
				if (kind === "atlas") refresh("debug", "fog", "sources");
				break;
			case "terrain":
			case "filters":
				refresh("state", "parts", "graph", "types", "search", "list", "heat");
				break;
			case "atlases":
				refresh("atlases");
				break;
			case "update":
				// a status request under way may answer older: dropped (CodeRabbit), and the newest kept
				void queryClient.cancelQueries({ queryKey: AppQueryKeys.update });
				keepUpdate(queryClient, data as UpdateStatus);
				break;
			case "lists":
				refresh("state", "recent");
				break;
			case "busy":
			case "watch":
			case "seams":
				refresh("state");
				break;
			case "bookmarks":
				refresh("bookmarks", "search", "info", "state");
				break;
			case "debug":
				refresh("debug");
				break;
			case "show_tab":
				useAppStore.getState().setTab(String(data));
				break;
		}
	};
}

/** Listens to the app's events until stopped; the browser reconnects by itself, and the state is fetched again. */
export function connectEvents(url: string, onEvent: (kind: EventKind, data: unknown) => void, onOpen: () => void) {
	const source = new EventSource(url);
	source.onopen = onOpen;
	for (const kind of EVENT_KINDS) {
		source.addEventListener(kind, (ev) => {
			const msg = ev as MessageEvent<string>;
			onEvent(kind, msg.data ? JSON.parse(msg.data) : null);
		});
	}
	return () => source.close();
}
