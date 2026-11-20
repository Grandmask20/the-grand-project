import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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
		const { user, calls } = renderWithApp(<UpdateButton />, {
			"GET /api/update": { ...base, latest: latest("1.3"), next: Date.now() / 1000 + 41.5 },
		});
		await user.click(await screen.findByRole("button", { name: /Up to date/i }));
		expect(screen.getByRole("button", { name: "Check again in 42 s" })).toBeDisabled();
		expect(calls.some((c) => c.path === "/api/update/check")).toBe(false);
		// closed and opened again: the same moment, not a new minute (it started again at 60: user)
		await user.keyboard("{Escape}");
		await user.click(screen.getByRole("button", { name: /Up to date/i }));
		expect(screen.getByRole("button", { name: /Check again in (41|42) s/ })).toBeDisabled();
	});
});
