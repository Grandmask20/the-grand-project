import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ColourSwatch } from "@/components/view/ColourSwatch";

describe("ColourSwatch", () => {
	it("shows the colour and hands back the one picked", () => {
		const onChange = vi.fn();
		render(<ColourSwatch label="Paths" value="#28d7ff" onChange={onChange} />);
		const input = screen.getByLabelText("Paths");
		expect(input).toHaveValue("#28d7ff");
		fireEvent.change(input, { target: { value: "#ff0000" } });
		expect(onChange).toHaveBeenCalledWith("#ff0000");
	});
});
