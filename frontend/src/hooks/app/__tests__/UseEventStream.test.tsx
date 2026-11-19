import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import type { AppState } from "@/domain/app/AppState";
import { useEventStream } from "@/hooks/app/UseEventStream";
import { renderWithApp } from "@/test/RenderWithApp";

/** An EventSource the test drives: open it, send events. */
class FakeSource {
	static last: FakeSource | null = null;
	url: string;
	onopen: (() => void) | null = null;
	closed = false;
	private listeners: Record<string, ((ev: MessageEvent<string>) => void)[]> = {};
	constructor(url: string) {
		this.url = url;
		FakeSource.last = this;
	}
	addEventListener(kind: string, fn: (ev: MessageEvent<string>) => void) {
		this.listeners[kind] = [...(this.listeners[kind] ?? []), fn];
	}
	send(kind: string, data: unknown) {
		for (const fn of this.listeners[kind] ?? []) fn({ data: JSON.stringify(data) } as MessageEvent<string>);
	}
	close() {
		this.closed = true;
	}
}

function Probe() {
	return <p>{useEventStream() ? "connected" : "waiting"}</p>;
}

describe("useEventStream", () => {
	beforeEach(() => vi.stubGlobal("EventSource", FakeSource));
	afterEach(() => vi.unstubAllGlobals());

	it("listens to the app's events while mounted", () => {
		const { queryClient, unmount } = renderWithApp(<Probe />);
		const src = FakeSource.last as FakeSource;
		expect(src.url).toBe("/api/events");
		expect(screen.getByText("waiting")).toBeInTheDocument();
		act(() => src.onopen?.());
		expect(screen.getByText("connected")).toBeInTheDocument();
		act(() => src.send("log", "12:05:00  added 2"));
		expect(queryClient.getQueryData<AppState>(AppQueryKeys.state)?.log.at(-1)).toBe("12:05:00  added 2");
		unmount();
		expect(src.closed).toBe(true);
	});

	it("after a reconnect, everything is fetched again", () => {
		const { queryClient } = renderWithApp(<Probe />);
		const spy = vi.spyOn(queryClient, "invalidateQueries");
		const src = FakeSource.last as FakeSource;
		act(() => src.onopen?.());
		expect(spy).toHaveBeenLastCalledWith({ queryKey: AppQueryKeys.state });
		act(() => src.onopen?.());
		expect(spy).toHaveBeenLastCalledWith();
	});
});
