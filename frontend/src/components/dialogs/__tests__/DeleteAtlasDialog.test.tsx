import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { DeleteAtlasDialog } from "@/components/dialogs/DeleteAtlasDialog";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const json = "/atlases/run/atlas.json";
const atlases = [{ name: "My run", json, numbers: { maps: 3, icons: 1, shots: 2 }, open: false, thumb: false }];

describe("DeleteAtlasDialog", () => {
	afterEach(resetStore);

	it("shows nothing until asked", () => {
		renderWithApp(<DeleteAtlasDialog />, { "GET /api/atlases": atlases });
		expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
	});

	it("names the atlas and only stops tracking it", async () => {
		useAppStore.getState().askDeleteAtlas(json);
		const { user, calls } = renderWithApp(<DeleteAtlasDialog />, {
			"GET /api/atlases": atlases,
			"POST /api/atlases/forget": { ok: true },
		});
		expect(await screen.findByText("What should happen to “My run”?")).toBeInTheDocument();
		expect(screen.getByText(/Your screenshots are never deleted/)).toBeInTheDocument();
		await user.click(screen.getByRole("button", { name: "Stop tracking atlas" }));
		await waitFor(() => expect(calls.find((c) => c.path === "/api/atlases/forget")?.body).toEqual({ json }));
		expect(calls.some((c) => c.path === "/api/atlases/delete")).toBe(false);
		expect(useAppStore.getState().deleteAtlas).toBeNull();
	});

	it("deletes only after a second click, and reports files it could not delete", async () => {
		useAppStore.getState().askDeleteAtlas(json);
		const { user, calls } = renderWithApp(<DeleteAtlasDialog />, {
			"GET /api/atlases": atlases,
			"POST /api/atlases/delete": { failed: ["atlas_files: in use"] },
		});
		await user.click(await screen.findByRole("button", { name: "Delete whole atlas and its data" }));
		expect(screen.getByText(/This can't be undone/)).toBeInTheDocument();
		expect(calls.some((c) => c.path === "/api/atlases/delete")).toBe(false);
		await user.click(screen.getByRole("button", { name: "Yes, delete it" }));
		await waitFor(() =>
			expect(useAppStore.getState().error).toBe("Some files could not be deleted:\natlas_files: in use"),
		);
		expect(calls.find((c) => c.path === "/api/atlases/delete")?.body).toEqual({ json });
	});
});
