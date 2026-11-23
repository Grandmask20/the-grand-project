import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GameIcon } from "@/components/common/GameIcon";

describe("GameIcon (one of the game's own interface icons)", () => {
	it("is a picture for the eye only, sized by its class", () => {
		const { container } = render(<GameIcon name="edit" className="size-4" />);
		const img = container.querySelector("img");
		expect(img).toHaveAttribute("alt", "");
		expect(img).toHaveAttribute("aria-hidden", "true");
		expect(img?.className).toContain("size-4");
		expect(img?.getAttribute("src")).toBeTruthy();
	});
});
