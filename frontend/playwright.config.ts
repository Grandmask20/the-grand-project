import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

/**
 * The browser tests: the real app (python -m grand_project) on a hand-made atlas, driven through the built page.
 * Build the page first (npm run build). PYTHON picks the interpreter (default: python3, or ../.venv's); with
 * E2E_COVERAGE=1 the app runs under coverage (settings in ../pyproject.toml). PW_CHROMIUM_PATH: a Chrome to use
 * instead of Playwright's own.
 */
// a port per run (the workers read this file again: they get it from the environment); the app won't reuse a
// port for a minute after it closed it, so a fixed one failed a second run straight after the first
process.env.E2E_PORT ??= String(20000 + Math.floor(Math.random() * 20000));
const PORT = Number(process.env.E2E_PORT);
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// tests/e2e_atlas.py empties it and makes the atlas (not here: this file is read again in every worker)
const work = resolve(root, "e2e-run");
const python = process.env.PYTHON ?? "python3";
const app = process.env.E2E_COVERAGE ? `${python} -m coverage run -m grand_project` : `${python} -m grand_project`;

export default defineConfig({
	testDir: "e2e",
	timeout: 60_000,
	expect: { timeout: 15_000 },
	fullyParallel: false,
	workers: 1, // one app, one atlas: the tests follow each other
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
	globalTeardown: "./e2e/Teardown.ts",
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		viewport: { width: 1600, height: 1000 },
		screenshot: "on",
		trace: "retain-on-failure",
		launchOptions: {
			executablePath: process.env.PW_CHROMIUM_PATH || undefined,
			// WebGL without a GPU (MapLibre): SwiftShader
			args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
		},
	},
	projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 1000 } } }],
	webServer: {
		command: `${python} -m tests.e2e_atlas "${work}" && ${app} "${work}/e2e/atlas.json" --no-browser --port ${PORT}`,
		cwd: root,
		env: { GRAND_PROJECT_USER_DATA: resolve(work, "user_data"), PYTHONUNBUFFERED: "1" },
		url: `http://127.0.0.1:${PORT}/api/meta`,
		timeout: 120_000,
		reuseExistingServer: false,
		stdout: "pipe",
	},
});
