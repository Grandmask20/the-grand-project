import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { MapTools } from "@/components/layout/MapTools";
import { useAppStore } from "@/store/AppStore";
import { state } from "@/test/Fixtures";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const tool = (name: string) => screen.getByRole("button", { name });

describe("MapTools", () => {
	afterEach(resetStore);

	it("Select is lit in the normal mode; a tool starts its mode and is lit, clicked again it ends", async () => {
		const { user } = renderWithApp(<MapTools />);
		expect(tool("Select")).toHaveAttribute("aria-pressed", "true");
		await user.click(tool("Biome"));
		expect(useAppStore.getState().mode).toEqual({ kind: "lasso" });
		expect(tool("Biome")).toHaveAttribute("aria-pressed", "true");
		expect(tool("Select")).toHaveAttribute("aria-pressed", "false");
		await user.click(tool("Biome"));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("each tool starts its own mode, and Select ends any", async () => {
		const { user } = renderWithApp(<MapTools />);
		await user.click(tool("Route"));
		expect(useAppStore.getState().mode).toEqual({ kind: "route", from: null });
		await user.click(tool("Bookmark"));
		expect(useAppStore.getState().mode).toEqual({ kind: "bookmark" });
		await user.click(tool("I am here"));
		expect(useAppStore.getState().mode).toEqual({ kind: "player" });
		await user.click(tool("Select"));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
	});

	it("Place asks for the screenshot to place by hand", async () => {
		const { user } = renderWithApp(<MapTools />);
		await user.click(tool("Place"));
		expect(useAppStore.getState().filePick?.title).toBe("Screenshot to place by hand");
	});

	it("no map tool while the timelapse is open (opening it ends one)", () => {
		renderWithApp(<MapTools />);
		act(() => useAppStore.getState().setMode({ kind: "route", from: null }));
		act(() => useAppStore.getState().setReplay({} as never));
		expect(useAppStore.getState().mode).toEqual({ kind: "normal" });
		expect(tool("Route")).toBeDisabled();
		expect(tool("Select")).toBeEnabled();
	});

	it("without an atlas, only Select", () => {
		renderWithApp(<MapTools />, { "GET /api/state": { ...state, atlas: null } });
		expect(tool("Bookmark")).toBeDisabled();
		expect(tool("Select")).toBeEnabled();
	});
});
