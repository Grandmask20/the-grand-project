import { describe, expect, it, vi } from "vitest";
import { ApiError, createHttp } from "@/api/Http";

const reply = (status: number, body: unknown) =>
	new Response(body === null ? "" : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("createHttp", () => {
	it("gets JSON with its query", async () => {
		const fetcher = vi.fn().mockResolvedValue(reply(200, { ok: 1 }));
		const http = createHttp("http://app", fetcher);
		expect(await http.get("/api/search", { q: "a b", skip: undefined })).toEqual({ ok: 1 });
		expect(fetcher).toHaveBeenCalledWith("http://app/api/search?q=a+b", { method: "GET" });
	});

	it("sends changes with the X-Grand header", async () => {
		const fetcher = vi.fn().mockResolvedValue(reply(200, null));
		await createHttp("", fetcher).send("POST", "/api/undo", { a: 1 });
		const [, init] = fetcher.mock.calls[0];
		expect(init.headers["X-Grand"]).toBe("1");
		expect(init.body).toBe('{"a":1}');
	});

	it("turns the app's errors into ApiError", async () => {
		const http = createHttp("", vi.fn().mockResolvedValue(reply(409, { error: "already a bookmark" })));
		await expect(http.send("POST", "/api/bookmarks", {})).rejects.toEqual(new ApiError("already a bookmark", 409));
		const down = createHttp("", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
		await expect(down.get("/api/state")).rejects.toMatchObject({ status: 0 });
	});
});
