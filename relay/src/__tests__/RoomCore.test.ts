import { describe, expect, it } from "vitest";
import {
	admit,
	announce,
	CLOSE_POLICY,
	forward,
	MAX_FRAME,
	MAX_WATCHERS,
	type Member,
	type Role,
	roleOf,
} from "../RoomCore";

/** A page in a room: what it was sent, and whether it was closed. */
function page(role: Role) {
	const got: string[] = [];
	const closed: number[] = [];
	const m: Member & { got: string[]; closed: number[] } = {
		role,
		got,
		closed,
		send: (t) => got.push(t),
		close: (code) => closed.push(code),
	};
	return m;
}

describe("RoomCore", () => {
	it("a role is share or watch", () => {
		expect([roleOf("share"), roleOf("watch"), roleOf("admin"), roleOf(null)]).toEqual(["share", "watch", null, null]);
	});

	it("one sharer per room, and so many watchers", () => {
		expect(admit([], "share")).toBeNull();
		expect(admit([page("share")], "share")).toBe("This room already has its sharer.");
		const full = Array.from({ length: MAX_WATCHERS }, () => page("watch"));
		expect(admit(full.slice(1), "watch")).toBeNull();
		expect(admit(full, "watch")).toMatch(/full/);
		expect(admit(full, "share")).toBeNull(); // (the sharer coming back to a full room)
	});

	it("the sharer's messages go to every watcher, a watcher's to the sharer only", () => {
		const [s, a, b] = [page("share"), page("watch"), page("watch")];
		forward(s, [s, a, b], "0:0:1:atlas");
		forward(a, [s, a, b], "0:0:1:hello");
		expect(s.got).toEqual(["0:0:1:hello"]);
		expect(a.got).toEqual(["0:0:1:atlas"]);
		expect(b.got).toEqual(["0:0:1:atlas"]); // (not a's hello: watchers don't hear each other)
	});

	it("what isn't a page's frame closes its sender: binary, too long, or passing itself off as the relay", () => {
		for (const bad of [new ArrayBuffer(4), "x".repeat(MAX_FRAME + 1), "!room:1:0"]) {
			const [s, a] = [page("share"), page("watch")];
			forward(s, [s, a], bad);
			expect(a.got).toEqual([]);
			expect(s.closed).toEqual([CLOSE_POLICY]);
		}
	});

	it("everyone is told who is there", () => {
		const [s, a, b] = [page("share"), page("watch"), page("watch")];
		announce([s, a, b]);
		expect([s.got, a.got, b.got]).toEqual([["!room:1:2"], ["!room:1:2"], ["!room:1:2"]]);
		announce([a]); // (the sharer and b left)
		expect(a.got.at(-1)).toBe("!room:0:1");
	});

	it("a page going away doesn't stop the others hearing", () => {
		const [s, a, b] = [page("share"), page("watch"), page("watch")];
		a.send = () => {
			throw new Error("closing");
		};
		forward(s, [s, a, b], "0:0:1:x");
		expect(b.got).toEqual(["0:0:1:x"]);
	});
});
