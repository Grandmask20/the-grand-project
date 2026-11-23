import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ShareButton } from "@/components/share/ShareButton";
import { resetShare, useShareStore } from "@/store/ShareStore";
import { renderWithApp } from "@/test/RenderWithApp";

const link = (id: number, state: "live" | "invited") => ({
	id,
	role: "share" as const,
	via: "room" as const,
	watchers: 0,
	epoch: 0,
	state,
	code: "",
	friend: "",
	atlas: null,
	player: null,
	updated: 0,
	error: "",
});

describe("ShareButton", () => {
	afterEach(resetShare);

	it("opens live sharing", async () => {
		const { user } = renderWithApp(<ShareButton />);
		await user.click(screen.getByRole("button", { name: "Share" }));
		expect(useShareStore.getState().open).toBe(true);
	});

	it("counts the links live", () => {
		useShareStore.setState({ links: [link(1, "live"), link(2, "invited"), link(3, "live")] });
		renderWithApp(<ShareButton />);
		expect(screen.getByRole("button", { name: "Share (2 live)" })).toBeInTheDocument();
	});
});
