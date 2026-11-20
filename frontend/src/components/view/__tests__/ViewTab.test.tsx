import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ViewTab } from "@/components/view/ViewTab";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

const frames = { legend: [], ramp: [], oldest: "", newest: "", heat_top: 1 };
const app = { "GET /api/replay/frames": frames };
const section = (name: RegExp) => screen.getByRole("button", { name });

describe("ViewTab", () => {
	afterEach(resetStore);

	it("is an accordion: Paths and Maps open to begin with, the others folded with what is set in them", () => {
		renderWithApp(<ViewTab />, app);
		expect(section(/^Paths/)).toHaveAttribute("aria-expanded", "true");
		expect(section(/^Maps/)).toHaveAttribute("aria-expanded", "true");
		expect(section(/^Background/)).toHaveAttribute("aria-expanded", "false");
		expect(section(/^Background/)).toHaveTextContent("Picture");
		expect(section(/^Side panel/)).toHaveTextContent("Left");
	});

	it("a title opens or folds its section, kept while the tab is closed", async () => {
		const { user, unmount } = renderWithApp(<ViewTab />, app);
		await user.click(section(/^Background/));
		expect(screen.getByRole("radio", { name: "Vector" })).toBeInTheDocument();
		await user.click(section(/^Paths/));
		expect(section(/^Paths/)).toHaveAttribute("aria-expanded", "false");
		unmount();
		renderWithApp(<ViewTab />, app);
		expect(section(/^Background/)).toHaveAttribute("aria-expanded", "true");
		expect(section(/^Paths/)).toHaveAttribute("aria-expanded", "false");
	});

	it("the 3D view's page has its own sections", async () => {
		const { user } = renderWithApp(<ViewTab />, app);
		await user.click(screen.getByRole("tab", { name: "3D view settings" }));
		expect(section(/^Paths/)).toHaveAttribute("aria-expanded", "true");
		expect(section(/^3D models/)).toHaveTextContent("size 1.0x");
	});

	it("locked while the timelapse is open, and says so", () => {
		renderWithApp(<ViewTab />, app);
		act(() => useAppStore.getState().setReplay({ recording: false } as never));
		expect(screen.getByText(/View settings are locked while the timelapse is open/)).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "Reset styles" })).toBeDisabled();
	});
});
