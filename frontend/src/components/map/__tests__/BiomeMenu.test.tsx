import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BiomeMenu } from "@/components/map/BiomeMenu";
import { meta } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("BiomeMenu", () => {
	it("names the maps inside and offers every biome, none, or cancel", async () => {
		const onChoose = vi.fn();
		const { user } = renderWithApp(<BiomeMenu x={5} y={5} maps={12} meta={meta} onChoose={onChoose} />);
		expect(screen.getByText("12 maps inside: their biome")).toBeInTheDocument();
		await user.click(screen.getByRole("menuitem", { name: "Vaal city" }));
		expect(onChoose).toHaveBeenCalledWith("Vaal city");
	});

	it("clears the maps' biome, or cancels", async () => {
		const onChoose = vi.fn();
		const { user } = renderWithApp(<BiomeMenu x={5} y={5} maps={1} meta={meta} onChoose={onChoose} />);
		await user.click(screen.getByRole("menuitem", { name: "Not a biome (clear these maps)" }));
		expect(onChoose).toHaveBeenCalledWith("");
	});
});
