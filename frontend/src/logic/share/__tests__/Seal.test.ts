import { describe, expect, it } from "vitest";
import { newRoom } from "@/logic/share/RoomCodes";
import { seal, sealKey, unseal } from "@/logic/share/Seal";

describe("Seal", () => {
	it("sealed text opens with the room's key, and reads as nothing like it", async () => {
		const key = await sealKey(newRoom().key);
		const text = JSON.stringify({ t: "hello", name: "Nyx" });
		const sealed = await seal(key, text);
		expect(sealed).not.toContain("Nyx");
		expect(await unseal(key, sealed)).toBe(text);
		expect(await seal(key, text)).not.toBe(sealed); // (a new IV each time)
	});

	it("another room's key, or a changed seal, doesn't open", async () => {
		const key = await sealKey(newRoom().key);
		const sealed = await seal(key, "atlas");
		await expect(unseal(await sealKey(newRoom().key), sealed)).rejects.toThrow();
		const flipped = sealed.slice(0, -2) + (sealed.at(-2) === "A" ? "B" : "A") + sealed.at(-1);
		await expect(unseal(key, flipped)).rejects.toThrow();
	});
});
