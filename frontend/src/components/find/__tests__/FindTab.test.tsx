import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FindTab } from "@/components/find/FindTab";
import { useAppStore } from "@/store/AppStore";
import { state, types } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const found = { results: [{ kind: "landmark", id: 2, label: "Vaal city (seen 3x)", x: 1, y: 2 }] };

describe("FindTab", () => {
	afterEach(resetStore);

	it("searches once typing settles and lists what it found", async () => {
		const { user, calls } = renderWithApp(<FindTab />, { "GET /api/types": types, "GET /api/search": found });
		await user.type(screen.getByLabelText("Find"), "vaal");
		expect(await screen.findByText('1 match(es) for "vaal"')).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Vaal city (seen 3x)" })).toBeInTheDocument();
		expect(calls.filter((c) => c.path === "/api/search").map((c) => c.params)).toEqual([{ q: "vaal" }]); // not per key
	});

	it("goes to coordinates and marks them", async () => {
		const { user } = renderWithApp(<FindTab />, { "GET /api/types": types, "GET /api/search": { goto: [120, -45] } });
		await user.type(screen.getByLabelText("Find"), "120, -45");
		expect(await screen.findByText("centred on 120, -45 (marked)")).toBeInTheDocument();
		expect(useAppStore.getState().goto).toEqual([120, -45]);
		expect(useAppStore.getState().fly).toMatchObject({ x: 120, y: -45 });
	});

	it("Esc and the clear button empty the search", async () => {
		const { user } = renderWithApp(<FindTab />, { "GET /api/types": types, "GET /api/search": found });
		const box = screen.getByLabelText("Find");
		await user.type(box, "vaal");
		await screen.findByText('1 match(es) for "vaal"');
		await user.keyboard("{Escape}");
		expect(box).toHaveValue("");
		await waitFor(() => expect(screen.queryByText(/match\(es\)/)).not.toBeInTheDocument());
		await user.type(box, "x");
		await user.click(screen.getByRole("button", { name: "Clear the search" }));
		expect(box).toHaveValue("");
	});

	it("the filters change the settings", async () => {
		const { user, calls } = renderWithApp(<FindTab />, {
			"GET /api/types": types,
			"PATCH /api/settings": (body: unknown) => ({ ...state.settings, ...(body as object) }), // the app answers with all of them
		});
		await user.click(screen.getByRole("switch", { name: "only what 2+ screenshots show" }));
		await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ multi_only: true }));
	});
});
