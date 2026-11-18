import { expect, type Page, test } from "@playwright/test";

/**
 * The page against the real app, on the hand-made atlas (tests/e2e_atlas.py: 15 maps, a Vaal city, one bookmark,
 * one screenshot). What the old Tk viewer test did in its window: the map draws, Find, selecting, bookmarks,
 * layers, the log, the screenshots of a spot.
 */

const errors: string[] = [];

async function open(page: Page) {
	page.on("pageerror", (e) => errors.push(`page error: ${e.message}`));
	page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
	await page.goto("/");
	await expect(page.getByRole("button", { name: /^Atlas: e2e/ })).toBeVisible();
	// the map: a canvas with a size (a collapsed container drew nothing once)
	const canvas = page.locator("canvas.maplibregl-canvas");
	await expect(canvas).toBeVisible();
	const box = await canvas.boundingBox();
	expect(box?.width ?? 0).toBeGreaterThan(400);
	expect(box?.height ?? 0).toBeGreaterThan(300);
	return canvas;
}

async function api<T>(page: Page, path: string): Promise<T> {
	const r = await page.request.get(path);
	expect(r.ok()).toBe(true);
	return (await r.json()) as T;
}

test.afterEach(() => {
	// the page logged no errors (the map's tile requests for empty spots answer 204, not errors)
	expect(errors).toEqual([]);
	errors.length = 0;
});

test("opens the atlas and draws the map", async ({ page }) => {
	await open(page);
	await expect(page.getByText(/\d+ maps · \d+ icons · \d+ landmarks · 1\s+screenshots/)).toBeVisible();
	await page.waitForTimeout(1500); // the tiles
	await page.screenshot({ path: test.info().outputPath("map.png") });
});

test("Find: searches, goes to a result and selects it", async ({ page }) => {
	await open(page);
	const find = page.getByRole("textbox", { name: "Find" });
	await find.fill("#3");
	await expect(page.getByText('1 match(es) for "#3"')).toBeVisible();
	await page.getByRole("button", { name: "Map #3", exact: true }).click();
	await expect(page.getByText("Selected", { exact: true })).toBeVisible();
	await expect(page.getByText(/^Map #3/).last()).toBeVisible();
	await find.fill("120, -45");
	await expect(page.getByText("centred on 120, -45 (marked)")).toBeVisible();
});

test("bookmarks: lists them, adds one on the map, saved in the atlas", async ({ page }) => {
	const canvas = await open(page);
	await page.getByRole("tab", { name: "Bookmarks" }).click();
	await expect(page.getByRole("button", { name: "farm <here>", exact: true })).toBeVisible();
	await page.getByRole("button", { name: "Add bookmark" }).click();
	const box = await canvas.boundingBox();
	if (!box) throw new Error("no map");
	await page.mouse.click(box.x + box.width * 0.3, box.y + box.height * 0.3);
	const dialog = page.getByRole("dialog");
	await expect(dialog).toBeVisible();
	await dialog.getByLabel("Name").fill("e2e spot");
	await dialog.getByLabel("Group").fill("E2E");
	await dialog.getByRole("button", { name: "Save" }).click();
	await expect(page.getByRole("button", { name: "e2e spot", exact: true })).toBeVisible();
	const saved = await api<{ groups: { name: string; items: { name: string }[] }[] }>(page, "/api/bookmarks");
	expect(saved.groups.find((g) => g.name === "E2E")?.items.map((b) => b.name)).toEqual(["e2e spot"]);
});

test("layers: switching one off is kept", async ({ page }) => {
	await open(page);
	const paths = page.locator("button[aria-pressed]", { hasText: /^Paths$/ }).first();
	if (!(await paths.isVisible())) await page.getByRole("button", { name: /^Layers/ }).click(); // the folded dock
	await expect(paths).toHaveAttribute("aria-pressed", "true");
	await paths.click();
	await expect(paths).toHaveAttribute("aria-pressed", "false");
	const s = await api<{ layers: Record<string, boolean> }>(page, "/api/settings");
	expect(s.layers.Paths).toBe(false);
	await paths.click();
	await expect(paths).toHaveAttribute("aria-pressed", "true");
});

test("the screenshots of a spot show the atlas's screenshot", async ({ page }) => {
	await open(page);
	const shots = await api<{ name: string; exists: boolean }[]>(page, "/api/sources?x=0&y=0");
	expect(shots.map((s) => [s.name, s.exists])).toEqual([["a", true]]);
	const jpeg = await page.request.get("/api/screenshot/a?w=320");
	expect(jpeg.headers()["content-type"]).toBe("image/jpeg");
	expect((await page.request.get("/api/screenshot/missing?w=320")).status()).toBe(204); // no picture
});

test("the log tells what happened", async ({ page }) => {
	await open(page);
	await page.getByRole("tab", { name: "Log" }).click();
	await expect(page.getByText(/opened atlas e2e/).first()).toBeVisible();
});
