import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LayersPopover } from "@/components/view/LayersPopover";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const settings = { "PATCH /api/settings": (b: unknown) => ({ ...state.settings, ...(b as object) }) };

describe("LayersPopover", () => {
	afterEach(resetStore);

	it("opens over the status line with every layer's switch and the colour legend", async () => {
		const { user } = renderWithApp(<LayersPopover />, settings);
		expect(screen.queryByRole("dialog")).toBeNull();
		await user.click(screen.getByRole("button", { name: "Layers" }));
		const box = screen.getByRole("dialog", { name: "Show on the map" });
		expect(box).toHaveTextContent("Paths");
		expect(box).toHaveTextContent("map: 1 shot");
		expect(screen.getByRole("button", { name: "Paths" })).toHaveAttribute("aria-pressed", "true");
		expect(screen.getByRole("button", { name: "Removed" })).toHaveAttribute("aria-pressed", "false");
		expect(screen.queryByRole("button", { name: "3D models" })).toBeNull(); // (the 3D view's: while tilted)
	});

	it("a switch saves the layer shown or hidden", async () => {
		const { user, calls } = renderWithApp(<LayersPopover />, settings);
		await user.click(screen.getByRole("button", { name: "Layers" }));
		await user.click(screen.getByRole("button", { name: "Paths" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/settings")?.body).toEqual({ layers: { Paths: false } }),
		);
	});

	it("Routes goes on, saved only, off", async () => {
		const { user, calls } = renderWithApp(<LayersPopover />, settings);
		await user.click(screen.getByRole("button", { name: "Layers" }));
		await user.click(screen.getByRole("button", { name: "Routes: on" }));
		await waitFor(() =>
			expect(calls.find((c) => c.path === "/api/settings")?.body).toEqual({
				layers: { Route: false, "Saved routes": true },
			}),
		);
	});

	it("closes on a click outside or Esc", async () => {
		const { user } = renderWithApp(
			<>
				<LayersPopover />
				<button type="button">elsewhere</button>
			</>,
			settings,
		);
		await user.click(screen.getByRole("button", { name: "Layers" }));
		await user.click(screen.getByRole("button", { name: "elsewhere" }));
		expect(screen.queryByRole("dialog")).toBeNull();
		await user.click(screen.getByRole("button", { name: "Layers" }));
		await user.keyboard("{Escape}");
		expect(screen.queryByRole("dialog")).toBeNull();
	});

	it("the layers stay as recorded while the timelapse records, and the 3D view lists its models", async () => {
		const { user } = renderWithApp(<LayersPopover />, settings);
		act(() => {
			useAppStore.setState({ camera: { x: 0, y: 0, px: 1, bearing: 0, pitch: 59 } });
			useAppStore.getState().setReplay({ recording: true } as never);
		});
		await user.click(screen.getByRole("button", { name: "Layers" }));
		expect(screen.getByRole("button", { name: "3D models" })).toBeDisabled();
	});
});
