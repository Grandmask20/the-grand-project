import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Section } from "@/components/common/Section";

describe("Section", () => {
	it("shows its title and what it holds", () => {
		render(<Section title="Paths">the sliders</Section>);
		expect(screen.getByRole("heading", { name: "Paths" })).toBeInTheDocument();
		expect(screen.getByText("the sliders")).toBeInTheDocument();
	});

	it("foldable: its title folds it away and opens it again", async () => {
		render(
			<Section foldable title="Paths" actions={<button type="button">reset</button>}>
				the sliders
			</Section>,
		);
		const title = screen.getByRole("button", { name: "Paths" });
		expect(title).toHaveAttribute("aria-expanded", "true");
		await userEvent.click(title);
		expect(screen.queryByText("the sliders")).toBeNull();
		expect(screen.queryByRole("button", { name: "reset" })).toBeNull();
		await userEvent.click(title);
		expect(screen.getByText("the sliders")).toBeInTheDocument();
	});

	it("can start folded", () => {
		render(
			<Section foldable startOpen={false} title="Maps">
				the sizes
			</Section>,
		);
		expect(screen.queryByText("the sizes")).toBeNull();
	});

	it("locked: greyed out and out of reach", () => {
		render(
			<Section locked title="Icons">
				<button type="button">size</button>
			</Section>,
		);
		expect(document.querySelector("section")).toHaveAttribute("aria-disabled", "true");
	});
});
