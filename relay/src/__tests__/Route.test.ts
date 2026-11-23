import { describe, expect, it } from "vitest";
import { originAllowed, roomOf } from "../Route";

describe("Route", () => {
	it("a room's path names it (22 URL-safe base64 characters), nothing else does", () => {
		expect(roomOf("/room/AbCdEfGhIjKlMnOpQrSt_-")).toBe("AbCdEfGhIjKlMnOpQrSt_-");
		for (const p of ["/", "/room/", "/room/short", "/room/AbCdEfGhIjKlMnOpQrSt_-/x", "/room/AbCdEfGhIjKlMnOpQrS!_-"])
			expect(roomOf(p)).toBeNull();
	});

	it("only the app's page comes in, on any port", () => {
		const allowed = "http://127.0.0.1, http://localhost/";
		expect(originAllowed("http://127.0.0.1:8765", allowed)).toBe(true);
		expect(originAllowed("http://localhost:8800", allowed)).toBe(true);
		expect(originAllowed("https://127.0.0.1:8765", allowed)).toBe(false);
		expect(originAllowed("https://evil.example", allowed)).toBe(false);
		expect(originAllowed(null, allowed)).toBe(false);
		expect(originAllowed("not a url", allowed)).toBe(false);
	});
});
