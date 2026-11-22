import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShareDialog } from "@/components/share/ShareDialog";
import { SharePeer } from "@/logic/share/SharePeer";
import { resetShare, sendTo, useShareStore } from "@/store/ShareStore";
import { FakeRtc } from "@/test/FakeRtc";
import { renderWithApp } from "@/test/RenderWithApp";
import { sharedAtlas } from "@/test/ShareAtlas";

const s = () => useShareStore.getState();
const share = () => screen.getByRole("region", { name: "Share my atlas" });
const watch = () => screen.getByRole("region", { name: "Watch a friend" });

describe("ShareDialog", () => {
	beforeEach(() => {
		SharePeer.Rtc = FakeRtc as unknown as typeof RTCPeerConnection;
		FakeRtc.slowIce = false;
		localStorage.clear();
		s().setOpen(true);
	});
	afterEach(resetShare);

	it("the name friends see, kept as typed", async () => {
		const { user } = renderWithApp(<ShareDialog />);
		await user.type(screen.getByLabelText("Your name"), "pl");
		expect(s().name).toBe("pl");
	});

	it("both sides in one page: invite, reply, connect, live; the watcher opens their atlas", async () => {
		const { user } = renderWithApp(<ShareDialog />);
		const writeText = vi.spyOn(navigator.clipboard, "writeText"); // (user-event's clipboard)

		await user.click(within(share()).getByRole("button", { name: "New invite" }));
		const invite = (await screen.findByLabelText("Your invite")) as HTMLTextAreaElement;
		expect(invite.value).toMatch(/^GPI1\./);
		await user.click(screen.getByRole("button", { name: "Copy" }));
		expect(writeText).toHaveBeenCalledWith(invite.value);

		await user.click(within(watch()).getByLabelText("Their invite"));
		await user.paste(invite.value);
		await user.click(within(watch()).getByRole("button", { name: "Join" }));
		const reply = (await screen.findByLabelText("Your reply")) as HTMLTextAreaElement;
		expect(reply.value).toMatch(/^GPR1\./);

		await user.click(screen.getByLabelText("Their reply"));
		await user.paste(reply.value);
		await user.click(screen.getByRole("button", { name: "Connect" }));
		await waitFor(() => expect(screen.getAllByText(/^live/)).toHaveLength(2));
		expect(screen.getByText("sees your atlas")).toBeInTheDocument();

		sendTo(s().links.find((l) => l.role === "share")?.id ?? -1, { t: "atlas", atlas: sharedAtlas });
		await user.click(await screen.findByRole("button", { name: "Open" }));
		expect(s().viewing).toBe(s().links.find((l) => l.role === "watch")?.id);
		expect(s().open).toBe(false);
	});

	it("a wrong code: said why, nothing kept", async () => {
		const { user } = renderWithApp(<ShareDialog />);
		await user.click(within(watch()).getByLabelText("Their invite"));
		await user.paste("hello");
		await user.click(within(watch()).getByRole("button", { name: "Join" }));
		expect(await screen.findByText("That isn't an invite code.")).toBeInTheDocument();
		expect(s().links).toEqual([]);
	});

	it("End removes a link", async () => {
		const { user } = renderWithApp(<ShareDialog />);
		await user.click(within(share()).getByRole("button", { name: "New invite" }));
		await screen.findByLabelText("Your invite");
		await user.click(screen.getByRole("button", { name: "End this link" }));
		expect(s().links).toEqual([]);
	});
});
