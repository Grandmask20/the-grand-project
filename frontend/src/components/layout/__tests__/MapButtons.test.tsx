import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GAME_PITCH, MapButtons } from "@/components/layout/MapButtons";
import { useAppStore } from "@/store/AppStore";
import { fakeMap } from "@/test/FakeMap";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const withMap = () => {
	const fm = fakeMap();
	act(() => useAppStore.getState().setMap(fm.map as never));
	return fm;
};

describe("MapButtons", () => {
	afterEach(resetStore);

	it("no map yet: only full screen works", () => {
		renderWithApp(<MapButtons />);
		expect(screen.getByRole("button", { name: "Zoom in" })).toBeDisabled();
		expect(screen.getByRole("button", { name: "Full screen" })).toBeEnabled();
	});

	it("zooms, faces north and fits the whole atlas", async () => {
		const { user } = renderWithApp(<MapButtons />);
		const fm = withMap();
		const zoom = fm.map.getZoom();
		await user.click(screen.getByRole("button", { name: "Zoom in" }));
		expect(fm.cam.zoom).toBe(zoom + 1);
		await user.click(screen.getByRole("button", { name: "Zoom out" }));
		expect(fm.cam.zoom).toBe(zoom);
		fm.cam.bearing = 30;
		await user.click(screen.getByRole("button", { name: "Face north" }));
		expect(fm.cam.bearing).toBe(0);
		await user.click(screen.getByRole("button", { name: "Fit the whole atlas (0)" }));
		expect(useAppStore.getState().fitAtlas).toBe(1);
	});

	it("3D tilts to the game's own camera and back, lit while tilted", async () => {
		const { user } = renderWithApp(<MapButtons />);
		const fm = withMap();
		const three = screen.getByRole("button", { name: /^3D view/ });
		await user.click(three);
		expect(fm.cam).toMatchObject({ pitch: GAME_PITCH, bearing: 0 });
		expect(three).toHaveAttribute("aria-pressed", "true");
		await user.click(three);
		expect(fm.cam.pitch).toBe(0);
		expect(three).toHaveAttribute("aria-pressed", "false");
	});

	it("full screen asks the browser for the whole page, and leaves it", async () => {
		const enter = vi.fn(async () => {
			Object.defineProperty(document, "fullscreenElement", { value: document.documentElement, configurable: true });
			document.dispatchEvent(new Event("fullscreenchange"));
		});
		const leave = vi.fn(async () => {
			Object.defineProperty(document, "fullscreenElement", { value: null, configurable: true });
			document.dispatchEvent(new Event("fullscreenchange"));
		});
		document.documentElement.requestFullscreen = enter;
		document.exitFullscreen = leave;
		const { user } = renderWithApp(<MapButtons />);
		await user.click(screen.getByRole("button", { name: "Full screen" }));
		expect(enter).toHaveBeenCalled();
		await user.click(screen.getByRole("button", { name: "Leave full screen" }));
		expect(leave).toHaveBeenCalled();
		expect(screen.getByRole("button", { name: "Full screen" })).toHaveAttribute("aria-pressed", "false");
	});
});
