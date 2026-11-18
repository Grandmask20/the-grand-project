import { connect } from "node:net";

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

/**
 * After the browser tests: ask the app to quit and wait until it has stopped, so it saved and, under coverage,
 * wrote its data (Playwright kills what is still running: CodeRabbit). Fails when it doesn't stop in time.
 */
export default async function teardown(): Promise<void> {
	const port = Number(process.env.E2E_PORT);
	try {
		await fetch(`http://127.0.0.1:${port}/api/quit`, { method: "POST", headers: { "X-Grand": "1" } });
	} catch {
		return; // already gone
	}
	const end = Date.now() + 60_000; // the app waits up to 30 s for work in progress, then saves
	while (await listening(port)) {
		if (Date.now() > end) throw new Error(`the app on port ${port} did not stop within 60 s of /api/quit`);
		await new Promise((r) => setTimeout(r, 250));
	}
	await new Promise((r) => setTimeout(r, 500)); // the listener closes before the process ends (coverage writes last)
}
