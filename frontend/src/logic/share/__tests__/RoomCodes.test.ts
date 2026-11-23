import { describe, expect, it } from "vitest";
import { ShareCodeError } from "@/logic/share/Codes";
import { isRoomCode, newRoom, parseRoom } from "@/logic/share/RoomCodes";

describe("RoomCodes", () => {
	it("a new room: its name for the relay, a 256-bit key, both in one code that reads back the same", () => {
		const r = newRoom();
		expect(r.room).toMatch(/^[A-Za-z0-9_-]{22}$/);
		expect(r.key).toHaveLength(32);
		expect(r.code).toMatch(/^GPS1\./);
		expect(parseRoom(`  ${r.code}\n`)).toEqual(r);
		expect(newRoom().room).not.toBe(r.room);
	});

	it("tells a room invite from a direct link's codes", () => {
		expect(isRoomCode(newRoom().code)).toBe(true);
		expect(isRoomCode("GPI1.zabc")).toBe(false);
	});

	it("a code that isn't one, or was cut short: said why", () => {
		expect(() => parseRoom("GPI1.zabc")).toThrow(new ShareCodeError("That isn't an invite code."));
		const { code } = newRoom();
		for (const bad of [
			code.slice(0, -5),
			code.replace(".", ".x"),
			`${code.split(".").slice(0, 2).join(".")}`,
			`${code}!`,
		])
			expect(() => parseRoom(bad)).toThrow("cut short or changed");
	});
});
