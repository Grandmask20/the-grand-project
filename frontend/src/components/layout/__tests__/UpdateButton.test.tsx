import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { keepUpdate, newerUpdate } from "@/api/EventStream";
import { pillOf, UpdateButton } from "@/components/layout/UpdateButton";
import type { UpdateStatus } from "@/domain/app/Update";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const base: UpdateStatus = {
	channel: "release",
	release: "1.3",
	program: "1.21",
	can: true,
	why: "",
	auto: true,
	checked: null,
	next: 0,
	seq: 1,
	run: 100,
	state: "idle",
	latest: null,
	available: false,
	error: null,
	got: 0,
	size: 0,
	just: null,
};
const latest = (release: string) => ({
	release,
	name: `The Grand Project ${release}`,
	notes: "What's new: routes",
	url: `https://github.com/x/y/releases/tag/v${release}`,
	published: "",
});

describe("UpdateButton", () => {
	afterEach(resetStore);

	it("says up to date in green, else check update, else the release to update to (user's mockup)", () => {
		expect(pillOf({ ...base, latest: latest("1.3") })).toEqual({ label: "Up to date", ok: true });
		expect(pillOf(base)).toEqual({ label: "Check update", ok: false });
		expect(pillOf({ ...base, latest: latest("1.4"), available: true }).label).toBe("Update to 1.4");
		expect(pillOf({ ...base, can: false, channel: "internal", release: null }).label).toBe("Check update");
	});

	it("the pill opens the box, Check now asks GitHub; a newer release can be put in place", async () => {
		const found = { ...base, latest: latest("1.4"), available: true, checked: 1 };
		const { user, calls } = renderWithApp(<UpdateButton />, {
			"GET /api/update": base,
			"POST /api/update/check": found,
			"POST /api/update/install": { ...found, state: "downloading" },
		});
		await user.click(await screen.findByRole("button", { name: /Check update.*1\.3/i }));
		expect(calls.some((c) => c.path === "/api/update/check")).toBe(false); // (the pill only opens the box: user)
		await user.click(screen.getByRole("button", { name: "Check now" }));
		expect(calls.some((c) => c.path === "/api/update/check")).toBe(true);
		expect(await screen.findByText("The Grand Project 1.4 is out.")).toBeInTheDocument();
		expect(screen.getByText("What's new: routes")).toBeInTheDocument();
		expect(screen.getByText("This copy: release 1.3")).toBeInTheDocument(); // (no program version: user)
		await user.click(screen.getByRole("button", { name: "Update now" }));
		await waitFor(() => expect(calls.some((c) => c.path === "/api/update/install")).toBe(true));
		expect(await screen.findByText(/Downloading… 0\.0 MB/)).toBeInTheDocument(); // (the box; the pill says it too)
	});

	it("a development copy says to use git, and checks nothing", async () => {
		const dev = {
			...base,
			channel: "internal",
			release: null,
			can: false,
			why: "This is a development copy: update it with git (git pull).",
		};
		const { user, calls } = renderWithApp(<UpdateButton />, { "GET /api/update": dev });
		await user.click(await screen.findByRole("button", { name: /1\.21/ }));
		expect(await screen.findByText(/update it with git/)).toBeInTheDocument();
		expect(calls.some((c) => c.path === "/api/update/check")).toBe(false);
	});

	it("the app back on another version: the page reloads itself", async () => {
		const reload = vi.fn();
		vi.stubGlobal("location", { ...window.location, reload });
		try {
			const { queryClient } = renderWithApp(<UpdateButton />, { "GET /api/update": base });
			await screen.findByRole("button", { name: /1\.3/ });
			queryClient.setQueryData(["update"], { ...base, release: "1.4" }); // (the release put in place)
			await waitFor(() => expect(reload).toHaveBeenCalled());
		} finally {
			vi.unstubAllGlobals();
		}
	});

	it("Check again waits out the minute between checks (GitHub's limit: quick clicks used it up, user)", async () => {
		// the clock stands still (a slow run took the countdown from 42 to 41: CodeRabbit)
		const now = Date.now();
		vi.spyOn(Date, "now").mockReturnValue(now);
		const { user, calls } = renderWithApp(<UpdateButton />, {
			"GET /api/update": { ...base, latest: latest("1.3"), next: now / 1000 + 41.5 },
		});
		await user.click(await screen.findByRole("button", { name: /Up to date/i }));
		expect(screen.getByRole("button", { name: "Check again in 42 s" })).toBeDisabled();
		expect(calls.some((c) => c.path === "/api/update/check")).toBe(false);
		// closed and opened again: the same moment, not a new minute (it started again at 60: user)
		await user.keyboard("{Escape}");
		await user.click(screen.getByRole("button", { name: /Up to date/i }));
		expect(screen.getByRole("button", { name: "Check again in 42 s" })).toBeDisabled();
		vi.restoreAllMocks();
	});

	it("an older status that lands later doesn't replace a newer one (CodeRabbit)", async () => {
		const { queryClient } = renderWithApp(<UpdateButton />, { "GET /api/update": { ...base, seq: 5 } });
		await screen.findByRole("button", { name: /Check update/i });
		keepUpdate(queryClient, { ...base, seq: 7, latest: latest("1.3") }); // (the event: done, up to date)
		keepUpdate(queryClient, { ...base, seq: 6, state: "checking" }); // (the button's answer, older)
		expect(await screen.findByRole("button", { name: /Up to date/i })).toBeInTheDocument();
	});

	it("a restarted app's status is newer, whatever its number (it starts again at 0: CodeRabbit)", () => {
		const old = { ...base, run: 100, seq: 40, state: "restarting" as const };
		expect(newerUpdate(old, { ...base, run: 200, seq: 1 }).run).toBe(200);
		expect(newerUpdate(old, { ...base, run: 100, seq: 39 })).toBe(old);
		expect(newerUpdate(undefined, old)).toBe(old);
	});

	it("shows a release's notes formatted, and the last update's line only while no newer one is offered", async () => {
		const notes = "## 1.3.2 Test\n\n- A test update\n- with **bold**";
		const just = { ok: true, from: "1.3", to: "1.3.1" };
		const found = { ...base, release: "1.3.1", latest: { ...latest("1.3.2"), notes }, available: true, just };
		const { user } = renderWithApp(<UpdateButton />, { "GET /api/update": found });
		await user.click(await screen.findByRole("button", { name: /Update to 1\.3\.2/i }));
		expect(screen.getByText("1.3.2 Test")).toBeInTheDocument(); // (a heading, not "## 1.3.2 Test": user)
		expect(screen.queryByText(/##/)).not.toBeInTheDocument();
		expect(screen.getAllByRole("listitem")).toHaveLength(2);
		expect(screen.getByText("bold").tagName).toBe("STRONG");
		expect(screen.queryByText(/Updated from release/)).not.toBeInTheDocument(); // (not beside "1.3.2 is out")
	});

	it("still says why an update failed beside the release it failed on", async () => {
		const just = { ok: false, from: "1.3.1", to: "1.3.2", error: "a file didn't match" };
		const found = { ...base, release: "1.3.1", latest: latest("1.3.2"), available: true, just };
		const { user } = renderWithApp(<UpdateButton />, { "GET /api/update": found });
		await user.click(await screen.findByRole("button", { name: /Update to 1\.3\.2/i }));
		expect(screen.getByText(/The update to 1\.3\.2 failed, nothing changed: a file didn't match/)).toBeInTheDocument();
	});
});
