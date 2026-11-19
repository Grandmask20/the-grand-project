import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TypeList } from "@/components/find/TypeList";
import { types } from "@/test/Fixtures";
import { renderWithApp } from "@/test/RenderWithApp";

describe("TypeList", () => {
	it("lists places and icons with their counts and ticks", async () => {
		renderWithApp(<TypeList onList={vi.fn()} />, { "GET /api/types": types });
		expect(await screen.findByText("Places")).toBeInTheDocument();
		expect(screen.getByRole("checkbox", { name: "Show Breach" })).toBeChecked();
		expect(screen.getByRole("checkbox", { name: "Show Ritual" })).not.toBeChecked(); // hidden in the settings
	});

	it("ticking a type saves it as shown", async () => {
		const { user, calls } = renderWithApp(<TypeList onList={vi.fn()} />, {
			"GET /api/types": types,
			"PATCH /api/settings": (b: unknown) => ({ ...(b as object) }),
		});
		await user.click(await screen.findByRole("checkbox", { name: "Show Ritual" }));
		await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ hidden_types: [] }));
	});

	it("clicking a name lists that type (icons with their picture's name)", async () => {
		const onList = vi.fn();
		const { user } = renderWithApp(<TypeList onList={onList} />, { "GET /api/types": types });
		await user.click(await screen.findByRole("button", { name: /Breach/ }));
		expect(onList).toHaveBeenCalledWith("Breach", "Breach");
		await user.click(screen.getByRole("button", { name: /City/ }));
		expect(onList).toHaveBeenCalledWith("City", null);
	});
});
