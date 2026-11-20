import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PromptDialog } from "@/components/dialogs/PromptDialog";
import { useAppStore } from "@/store/AppStore";
import { resetStore } from "@/test/RenderWithApp";

describe("PromptDialog", () => {
	afterEach(resetStore);

	it("shows nothing until asked", () => {
		render(<PromptDialog />);
		expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
	});

	it("starts with the given text and hands back what was typed, trimmed", async () => {
		const onOk = vi.fn();
		useAppStore.getState().ask({ title: "New group", label: "Group name", value: "Farm", onOk });
		render(<PromptDialog />);
		const box = screen.getByLabelText("Group name");
		expect(box).toHaveValue("Farm");
		await userEvent.clear(box);
		await userEvent.type(box, "  Bosses  {Enter}");
		expect(onOk).toHaveBeenCalledWith("Bosses");
		expect(useAppStore.getState().prompt).toBeNull();
	});

	it("an empty answer is handed back too (an optional note: OK did nothing without one, user)", async () => {
		const onOk = vi.fn();
		useAppStore.getState().ask({ title: "Debug mark", label: "Note (optional)", value: "", onOk });
		render(<PromptDialog />);
		await userEvent.click(screen.getByRole("button", { name: "OK" }));
		expect(onOk).toHaveBeenCalledWith("");
	});

	it("offers the given choices", () => {
		useAppStore.getState().ask({ title: "Move", label: "Group", value: "", options: ["Boss", "Farm"], onOk: vi.fn() });
		const { baseElement } = render(<PromptDialog />);
		expect([...baseElement.querySelectorAll("datalist option")].map((o) => o.getAttribute("value"))).toEqual([
			"Boss",
			"Farm",
		]);
	});

	it("cancel hands back nothing", async () => {
		const onOk = vi.fn();
		useAppStore.getState().ask({ title: "Rename", label: "Name", value: "x", onOk });
		render(<PromptDialog />);
		await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
		expect(onOk).not.toHaveBeenCalled();
		expect(useAppStore.getState().prompt).toBeNull();
	});
});
