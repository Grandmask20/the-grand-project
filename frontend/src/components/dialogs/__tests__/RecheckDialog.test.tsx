import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecheckDialog } from "@/components/dialogs/RecheckDialog";
import type { RecheckInfo } from "@/domain/app/RecheckInfo";
import { useAppStore } from "@/store/AppStore";
import { atlases } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

const now = Date.now() / 1000;
const info: RecheckInfo = {
	last_check: { time: now - 3 * 86400, version: "1.23" },
	shots: 40,
	detect: 30,
	missing: 2,
	estimate_s: 95,
	groups: [
		{ version: "1.23", fresh: true, count: 10, newest: now - 3600, oldest: now - 3600 },
		{ version: null, fresh: false, count: 30, newest: now - 2 * 86400, oldest: now - 9 * 86400 },
	],
};

function open(json: string, routes = {}) {
	const r = renderWithApp(<RecheckDialog />, {
		"GET /api/atlases": atlases,
		"GET /api/atlas/recheck-info": info,
		"POST /api/atlas/recheck": { ok: true },
		"POST /api/atlas/recheck-file": { ok: true },
		...routes,
	});
	act(() => useAppStore.getState().askRecheck(json));
	return r;
}

describe("RecheckDialog", () => {
	it("says when the atlas and its screenshots were checked, what will be detected again and how long", async () => {
		const { calls } = open("/atlases/default/atlas.json");
		expect(await screen.findByText("3 days ago (v1.23)")).toBeInTheDocument();
		expect(screen.getByText("10 detected 1 hour ago on v1.23")).toBeInTheDocument();
		expect(
			screen.getByText("30 detected 9 days ago to 2 days ago on an unrecorded version (before 1.23)"),
		).toBeInTheDocument();
		expect(screen.getByText(/older detector: detected again/)).toBeInTheDocument();
		expect(screen.getByText(/2 screenshot file\(s\) are gone/)).toBeInTheDocument();
		expect(screen.getByText(/30 of 40 screenshots will be detected again/)).toBeInTheDocument();
		expect(screen.getByText("about 2 minutes")).toBeInTheDocument();
		expect(calls.find((c) => c.path === "/api/atlas/recheck-info")?.params).toEqual({
			path: "/atlases/default/atlas.json",
		});
	});

	it("re-checks the open atlas on Re-check, nothing on Cancel", async () => {
		const { user, calls } = open("/atlases/default/atlas.json");
		await user.click(await screen.findByRole("button", { name: "Cancel" }));
		expect(useAppStore.getState().recheckAtlas).toBeNull();
		expect(calls.some((c) => c.path === "/api/atlas/recheck")).toBe(false);
		act(() => useAppStore.getState().askRecheck("/atlases/default/atlas.json"));
		await user.click(await screen.findByRole("button", { name: "Re-check" }));
		await waitFor(() => expect(calls.some((c) => c.path === "/api/atlas/recheck")).toBe(true));
	});

	it("opens another atlas first", async () => {
		const { user, calls } = open("/atlases/two/atlas.json");
		expect(await screen.findByText(/“second” is opened first/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Re-check" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/atlas/recheck-file")?.body).toEqual({
				path: "/atlases/two/atlas.json",
			}),
		);
	});
});
