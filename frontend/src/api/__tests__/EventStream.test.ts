import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { createEventHandler } from "@/api/EventStream";
import type { AppState } from "@/domain/app/AppState";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";

describe("createEventHandler", () => {
	afterEach(() => vi.useRealTimers());

	it("patches the log, progress and questions in place", () => {
		const qc = new QueryClient();
		qc.setQueryData(AppQueryKeys.state, structuredClone(state));
		const handle = createEventHandler(qc);
		handle("log", "12:01:00  added");
		handle("progress", "placing");
		handle("question", { id: 7, question: "Add it?", preview: null });
		let s = qc.getQueryData<AppState>(AppQueryKeys.state);
		expect(s?.log.at(-1)).toBe("12:01:00  added");
		expect(s?.progress).toBe("placing");
		expect(s?.questions.map((q) => q.id)).toEqual([7]);
		handle("answered", { id: 7 });
		s = qc.getQueryData<AppState>(AppQueryKeys.state);
		expect(s?.questions).toEqual([]);
	});

	it("refetches what a change touches, once for a burst", () => {
		vi.useFakeTimers();
		const qc = new QueryClient();
		const spy = vi.spyOn(qc, "invalidateQueries");
		const handle = createEventHandler(qc);
		handle("model", 4);
		handle("model", 5);
		expect(spy).not.toHaveBeenCalled();
		vi.advanceTimersByTime(200);
		const keys = spy.mock.calls.map((c: unknown[]) => (c[0] as { queryKey?: unknown[] } | undefined)?.queryKey?.[0]);
		expect(keys.filter((k: unknown) => k === "state")).toHaveLength(1);
		expect(keys).toContain("graph");
	});

	it("opens the tab the app asks for", () => {
		createEventHandler(new QueryClient())("show_tab", "auto");
		expect(useAppStore.getState().tab).toBe("auto");
	});
});
