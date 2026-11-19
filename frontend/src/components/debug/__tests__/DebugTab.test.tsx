import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DebugTab } from "@/components/debug/DebugTab";
import type { DebugMarks } from "@/domain/debug/DebugMarks";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const marks: DebugMarks = {
	enabled: true,
	file: "atlas_debug.json",
	reasons: {},
	marks: [
		{
			id: 1,
			time: "",
			kind: "map",
			reason: "missing",
			note: "behind the tower",
			x: 12.4,
			y: -3.6,
			maps: [],
			screenshots: [],
		},
		{ id: 2, time: "", kind: "path", reason: "wrong", note: "", x: 100, y: 200, maps: [], screenshots: [] },
	],
};

describe("DebugTab", () => {
	afterEach(resetStore);

	it("lists the marks and goes to one", async () => {
		const { user } = renderWithApp(<DebugTab />, { "GET /api/debug": marks });
		expect(await screen.findByText(/2 mark\(s\) in atlas_debug\.json/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "D1 map: missing - behind the tower (12, -4)" }));
		expect(useAppStore.getState().fly).toMatchObject({ x: 12.4, y: -3.6, px: 1 });
	});

	it("deletes one mark", async () => {
		const { user, calls } = renderWithApp(<DebugTab />, {
			"GET /api/debug": marks,
			"DELETE /api/debug/2": { ok: true },
		});
		await screen.findByText(/D2 path: wrong/);
		await user.click(screen.getAllByRole("button", { name: "Delete" })[1]);
		await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/debug/2")).toBe(true));
	});

	it("clears every mark after asking", async () => {
		const { user, calls } = renderWithApp(<DebugTab />, {
			"GET /api/debug": marks,
			"POST /api/debug/clear": { backup: "x" },
		});
		await user.click(await screen.findByRole("button", { name: "Clear all…" }));
		const ask = useAppStore.getState().confirm;
		expect(ask?.text).toMatch(/^Delete all 2 debug marks/);
		ask?.onYes();
		await waitFor(() => expect(calls.some((c) => c.path === "/api/debug/clear")).toBe(true));
	});

	it("nothing to clear without marks; hides them on the map", async () => {
		const { user, calls } = renderWithApp(<DebugTab />, {
			"GET /api/debug": { ...marks, marks: [] },
			"PATCH /api/settings": (body: unknown) => ({ ...state.settings, ...(body as object) }), // the app answers with all of them
		});
		expect(await screen.findByRole("button", { name: "Clear all…" })).toBeDisabled();
		await user.click(screen.getByRole("button", { name: "Hide on the map" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/settings")?.body).toEqual({ layers: { "Debug marks": false } }),
		);
	});
});
