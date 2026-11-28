import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ExperimentalTab } from "@/components/experimental/ExperimentalTab";
import { meta, state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

// the app answers with all the settings, the change merged
const patch = (body: unknown) => ({
	...state.settings,
	detection: { ...state.settings.detection, ...(body as { detection: object }).detection },
});
const sent = (calls: { path: string; body?: unknown }[]) =>
	calls.filter((c) => c.path === "/api/settings").map((c) => c.body);

describe("ExperimentalTab", () => {
	afterEach(resetStore);

	it("saves the workers within this computer's cores when the box is left, and says a restart applies it", async () => {
		const { user, calls } = renderWithApp(<ExperimentalTab />, { "PATCH /api/settings": patch });
		expect(screen.queryByRole("status")).not.toBeInTheDocument(); // (saved = what this run uses)
		const box = screen.getByRole("spinbutton", { name: "Max workers" });
		await user.clear(box);
		await user.type(box, "99{Enter}");
		await waitFor(() => expect(sent(calls)).toEqual([{ detection: { workers: 7 } }])); // (at most max_workers)
		expect(await screen.findByRole("status")).toHaveTextContent("restart the app to apply");
	});

	it("saves the model only when it changed, and leaves no text that is not a number in the workers box", async () => {
		const { user, calls } = renderWithApp(<ExperimentalTab />, { "PATCH /api/settings": patch });
		const workers = screen.getByRole("spinbutton", { name: "Max workers" });
		await user.clear(workers);
		await user.tab(); // (empty: not a number)
		expect(workers).toHaveValue(4);
		const model = screen.getByRole("textbox", { name: "RF-DETR model" });
		expect(model).toHaveAttribute("placeholder", meta.detection.default_model);
		await user.click(model);
		await user.tab(); // (left unchanged: nothing sent)
		await user.type(model, " me/model ");
		await user.tab();
		await waitFor(() => expect(sent(calls)).toEqual([{ detection: { model: "me/model" } }]));
	});

	it("turns RF-DETR on", async () => {
		const { user, calls } = renderWithApp(<ExperimentalTab />, { "PATCH /api/settings": patch });
		await user.click(screen.getByRole("switch", { name: "RF-DETR detection" }));
		await waitFor(() => expect(sent(calls)).toEqual([{ detection: { rf_detr: true } }]));
	});

	it("greys RF-DETR out where its packages are missing", () => {
		renderWithApp(<ExperimentalTab />, {
			"GET /api/meta": { ...meta, detection: { ...meta.detection, rf_detr_missing: "torch" } },
		});
		expect(screen.getByRole("switch", { name: "RF-DETR detection" })).toBeDisabled();
		expect(screen.getByText(/Needs torch/)).toBeInTheDocument();
	});
});
