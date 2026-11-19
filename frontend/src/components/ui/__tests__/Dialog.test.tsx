import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

/** A dialog opened from code (as the store opens them), not by a Radix trigger. */
function Page() {
	const [open, setOpen] = useState(false);
	return (
		<>
			<button type="button">first</button>
			<button type="button" onClick={() => setOpen(true)}>
				opener
			</button>
			<Dialog open={open} onOpenChange={setOpen}>
				<DialogContent>
					<DialogTitle>Sure?</DialogTitle>
					<button type="button" onClick={() => setOpen(false)}>
						ok
					</button>
				</DialogContent>
			</Dialog>
		</>
	);
}

describe("DialogContent", () => {
	it("gives the focus back to the control that opened it", async () => {
		const user = userEvent.setup();
		render(<Page />);
		screen.getByRole("button", { name: "first" }).focus(); // (focused when the page was drawn: it went there)
		await user.click(screen.getByRole("button", { name: "opener" }));
		await user.click(await screen.findByRole("button", { name: "ok" }));
		await waitFor(() => expect(screen.getByRole("button", { name: "opener" })).toHaveFocus());
	});
});
