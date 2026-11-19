import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "@/components/dialogs/ConfirmDialog";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

describe("ConfirmDialog", () => {
	afterEach(resetStore);

	it("shows nothing until asked", () => {
		render(<ConfirmDialog />);
		expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
	});

	it("does it on yes, and closes", async () => {
		const onYes = vi.fn();
		useAppStore
			.getState()
			.askConfirm({ title: "Delete?", text: "Delete 2 bookmarks?", yes: "Delete", danger: true, onYes });
		render(<ConfirmDialog />);
		expect(screen.getByRole("dialog", { name: "Delete?" })).toHaveTextContent("Delete 2 bookmarks?");
		await userEvent.click(screen.getByRole("button", { name: "Delete" }));
		expect(onYes).toHaveBeenCalledOnce();
		expect(useAppStore.getState().confirm).toBeNull();
	});

	it("does nothing on cancel", async () => {
		const onYes = vi.fn();
		useAppStore.getState().askConfirm({ title: "Sure?", text: "", yes: "Go", onYes });
		render(<ConfirmDialog />);
		await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
		expect(onYes).not.toHaveBeenCalled();
		expect(useAppStore.getState().confirm).toBeNull();
	});
});
