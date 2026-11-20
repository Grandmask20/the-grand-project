import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { PagePicker, pageIds } from "@/components/common/PagePicker";

function Pages() {
	const [page, setPage] = useState<"a" | "b" | "c">("a");
	return (
		<>
			<PagePicker
				label="Pages"
				pages={[
					["a", "A"],
					["b", "B"],
					["c", "C"],
				]}
				value={page}
				onChange={setPage}
				idBase="p"
			/>
			<div id={pageIds("p", page).panel} role="tabpanel" aria-labelledby={pageIds("p", page).tab}>
				page {page}
			</div>
		</>
	);
}

describe("PagePicker", () => {
	it("is one Tab stop; the arrow keys, Home and End move and pick; the page is tied to its button (CodeRabbit)", async () => {
		render(<Pages />);
		const user = userEvent.setup();
		await user.tab();
		expect(screen.getByRole("tab", { name: "A" })).toHaveFocus();
		expect(screen.getByRole("tab", { name: "B" })).toHaveAttribute("tabindex", "-1");
		await user.keyboard("{ArrowRight}");
		expect(screen.getByRole("tab", { name: "B" })).toHaveFocus();
		expect(screen.getByRole("tabpanel", { name: "B" })).toHaveTextContent("page b");
		await user.keyboard("{End}");
		expect(screen.getByRole("tab", { name: "C" })).toHaveAttribute("aria-selected", "true");
		await user.keyboard("{ArrowRight}"); // (round to the first)
		expect(screen.getByRole("tab", { name: "A" })).toHaveFocus();
	});
});
