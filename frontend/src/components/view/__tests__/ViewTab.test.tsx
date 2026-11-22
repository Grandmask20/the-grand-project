import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ViewTab } from "@/components/view/ViewTab";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("ViewTab", () => {
	afterEach(resetStore);

	it("3D view settings, Ground: sky and fog, on at first; off, it is saved", async () => {
		useAppStore.setState({ pages: { view: "3d" }, viewOpen: ["3d:Ground"] });
		const { user, calls } = renderWithApp(<ViewTab />, {
			"PATCH /api/settings": (body: unknown) => ({ ...state.settings, ...(body as object) }),
		});
		const sky = await screen.findByRole("switch", { name: "sky and fog" });
		expect(sky).toBeChecked();
		await user.click(sky);
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/settings")?.body).toMatchObject({ style: { d3_sky: false } }),
		);
	});
});
