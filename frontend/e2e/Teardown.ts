import { readdirSync } from "node:fs";
import { connect } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** The program folder: the app runs there, and under coverage writes its data files there. */
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

/** Whether something still accepts connections on the port (the app, until it has saved and stopped). */
function listening(port: number): Promise<boolean> {
	return new Promise((done) => {
		const socket = connect({ host: "127.0.0.1", port });
		socket.once("connect", () => {
			socket.destroy();
			done(true);
		});
		socket.once("error", () => done(false)); // refused: stopped
	});
}

/** Coverage's data files in the program folder (parallel mode: one per process, written as it exits). */
const coverageFiles = () => readdirSync(ROOT).filter((f) => f.startsWith(".coverage."));

/**
 * After the browser tests: ask the app to quit and wait until it has stopped, so it saved and, under coverage,
 * wrote its data (Playwright kills what is still running: CodeRabbit). Waits on what shows each step is done, not on
 * a guess: the port refusing connections (saved and stopped serving), then, under coverage, the app's data file
 * there with no SQLite journal beside it (written whole: a fixed 500 ms was a guess, CodeRabbit). Fails when that
 * doesn't happen within the deadline.
 */
export default async function teardown(): Promise<void> {
	const port = Number(process.env.E2E_PORT);
	const before = new Set(coverageFiles());
	try {
		await fetch(`http://127.0.0.1:${port}/api/quit`, { method: "POST", headers: { "X-Grand": "1" } });
	} catch {
		return; // already gone
	}
	const end = Date.now() + 60_000; // the app waits up to 30 s for work in progress, then saves
	const pause = () => new Promise((r) => setTimeout(r, 100)); // (how often to look, not how long to wait)
	while (await listening(port)) {
		if (Date.now() > end) throw new Error(`the app on port ${port} did not stop within 60 s of /api/quit`);
		await pause();
	}
	if (!process.env.E2E_COVERAGE) return;
	for (;;) {
		const fresh = coverageFiles().filter((f) => !before.has(f));
		if (fresh.some((f) => !f.endsWith("-journal")) && !fresh.some((f) => f.endsWith("-journal"))) return;
		if (Date.now() > end) throw new Error("the app stopped but its coverage data was not written within 60 s");
		await pause();
	}
}
