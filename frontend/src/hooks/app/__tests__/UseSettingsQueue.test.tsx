import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SettingsChange } from "@/domain/app/UiSettings";
import { merge, useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useTypes } from "@/hooks/find/UseTypes";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

function Probe() {
	const settings = useSettings();
	const update = useUpdateSettings();
	return (
		<>
			<button type="button" onClick={() => update.mutate({ hidden_types: ["A"] })}>
				hide A
			</button>
			<button type="button" onClick={() => update.mutate({ hidden_types: ["A", "B"] })}>
				hide B
			</button>
			<p data-testid="hidden">{settings?.hidden_types.join(",")}</p>
		</>
	);
}

describe("useUpdateSettings, quick changes", () => {
	afterEach(resetStore);

	it("keeps a change still on its way when the answer to an earlier one comes", async () => {
		// each PATCH answers when the test says (the app's settings as after that change)
		const pending: (() => void)[] = [];
		let saved = state.settings;
		const { user, calls } = renderWithApp(<Probe />, {
			"PATCH /api/settings": (body: unknown) =>
				new Promise((resolve) => {
					pending.push(() => {
						saved = merge(saved, body as SettingsChange);
						resolve(saved);
					});
				}),
		});
		await user.click(screen.getByRole("button", { name: "hide A" }));
		await user.click(screen.getByRole("button", { name: "hide B" }));
		expect(screen.getByTestId("hidden").textContent).toBe("A,B");
		await waitFor(() => expect(pending).toHaveLength(1));
		// the first answer ("A" hidden) lands while "B" waits its turn: the page still shows both (user: a tick
		// showed the one before it)
		await act(async () => pending[0]());
		await waitFor(() => expect(pending).toHaveLength(2));
		expect(screen.getByTestId("hidden").textContent).toBe("A,B");
		await act(async () => pending[1]());
		await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(2));
		expect(screen.getByTestId("hidden").textContent).toBe("A,B");
	});

	it("fetches Find's type list again only when a change can change it", async () => {
		const { user, calls } = renderWithApp(<LookProbe />, {
			"PATCH /api/settings": (body: unknown) => merge(state.settings, body as SettingsChange),
			"GET /api/types": { sections: [] },
		});
		const typeFetches = () => calls.filter((c) => c.path === "/api/types").length;
		await waitFor(() => expect(typeFetches()).toBe(1)); // the list's own first fetch
		await user.click(screen.getByRole("button", { name: "wider" }));
		await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
		await new Promise((r) => setTimeout(r, 0));
		expect(typeFetches()).toBe(1);
		await user.click(screen.getByRole("button", { name: "near" }));
		await waitFor(() => expect(typeFetches()).toBe(2));
	});
});

function LookProbe() {
	const update = useUpdateSettings();
	useTypes();
	return (
		<>
			<button type="button" onClick={() => update.mutate({ style: { path_width: 3 } })}>
				wider
			</button>
			<button type="button" onClick={() => update.mutate({ near_only: true })}>
				near
			</button>
		</>
	);
}
