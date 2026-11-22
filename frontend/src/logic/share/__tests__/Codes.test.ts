import { describe, expect, it, vi } from "vitest";
import { packCode, ShareCodeError, unpackCode } from "@/logic/share/Codes";

const offer = {
	type: "offer" as RTCSdpType,
	sdp: `v=0\r\n${"a=candidate:1 1 udp 2122 192.168.1.20 50000 typ host\r\n".repeat(8)}`,
};

describe("Codes", () => {
	it("an invite comes back as the offer it was made from, squeezed shorter than it", async () => {
		const code = await packCode("invite", offer);
		expect(code).toMatch(/^GPI1\.[zp][A-Za-z0-9_-]+$/);
		expect(await unpackCode("invite", code)).toEqual(offer);
		expect(code[5]).toBe("z"); // (deflated)
		expect(code.length).toBeLessThan((offer.sdp?.length ?? 0) / 2);
	});

	it("a browser without deflate writes it plain, and any reads it", async () => {
		vi.stubGlobal("CompressionStream", undefined);
		const code = await packCode("invite", offer);
		vi.unstubAllGlobals();
		expect(code.startsWith("GPI1.p")).toBe(true);
		expect(await unpackCode("invite", code)).toEqual(offer);
	});

	it("spaces and line breaks a chat added are ignored", async () => {
		const code = await packCode("reply", { type: "answer", sdp: "v=0 answer" });
		const mangled = `  ${code.slice(0, 10)}\n${code.slice(10)} `;
		expect(await unpackCode("reply", mangled)).toEqual({ type: "answer", sdp: "v=0 answer" });
	});

	it("the wrong code in the wrong box, or a code cut short, is said so", async () => {
		const invite = await packCode("invite", offer);
		await expect(unpackCode("reply", invite)).rejects.toThrow("That's an invite");
		await expect(unpackCode("invite", "GPR1.zabc")).rejects.toThrow("That's a reply code");
		await expect(unpackCode("invite", "hello")).rejects.toBeInstanceOf(ShareCodeError);
		await expect(unpackCode("invite", invite.slice(0, 20))).rejects.toThrow("cut short");
	});
});
