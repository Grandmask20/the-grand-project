import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { Section } from "@/components/common/Section";
import { ViewTab } from "@/components/view/ViewTab";
import { useAppStore } from "@/store/AppStore";
import { renderWithApp, resetStore } from "@/test/RenderWithApp";

describe("Section", () => {
	afterEach(resetStore);

	it("a plain one shows its title and what is in it", () => {
		render(<Section title="Paths">inside</Section>);
		expect(screen.getByRole("heading", { name: "Paths" })).toBeInTheDocument();
		expect(screen.getByText("inside")).toBeInTheDocument();
	});

	it("a foldable one starts folded with its summary, and its title opens it", async () => {
		const user = userEvent.setup();
		render(
			<Section title="Paths" foldable summary="dashed · auto width">
				inside
			</Section>,
		);
		const title = screen.getByRole("button", { name: /Paths/ });
		expect(title).toHaveAttribute("aria-expanded", "false");
		expect(screen.getByText("dashed · auto width")).toBeInTheDocument();
		expect(screen.queryByText("inside")).not.toBeInTheDocument();
		await user.click(title);
		expect(screen.getByText("inside")).toBeInTheDocument();
		expect(screen.queryByText("dashed · auto width")).not.toBeInTheDocument();
	});

	it("the View tab's sections are all folded on first open, and stay as left (user)", async () => {
		const { user, unmount } = renderWithApp(<ViewTab />);
		const background = await screen.findByRole("button", { name: /Background/ });
		const all = screen.getAllByRole("button", { expanded: false });
		expect(all.length).toBeGreaterThanOrEqual(6); // background, side panel, paths, icons, maps, cities, colour by
		expect(screen.queryByRole("button", { expanded: true })).not.toBeInTheDocument();
		await user.click(background);
		expect(useAppStore.getState().viewOpen).toEqual(["2d:Background"]);
		unmount();
		renderWithApp(<ViewTab />);
		expect(await screen.findByRole("button", { name: /Background/ })).toHaveAttribute("aria-expanded", "true");
	});
});
