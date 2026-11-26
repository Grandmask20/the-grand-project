"use strict";
/**
 * The desktop app: a window on the program's page, with the program (frozen by PyInstaller) started beside it and
 * stopped when the window closes, and on Windows the update put in place by itself (electron-updater, from the GitHub
 * release's assets: .github/workflows/desktop.yml). The page and the program are the same as in the browser.
 */
const { app, BrowserWindow, dialog, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { backendCommand, backendEnv, findUrl, handedOver } = require("./lib/backend");

const START_WAIT_MS = 90_000; // the program's first start (unpacking its libraries on a slow disk) can take a while
const QUIT_WAIT_MS = 30_000; // it saves the open atlas before it stops (app/server.py: /api/quit)
const STARTING_PAGE = `data:text/html;charset=utf-8,${encodeURIComponent(
	"<body style='margin:0;display:grid;place-items:center;height:100vh;background:#0b0b0f;color:#c8aa6e;" +
		"font:16px system-ui'>Starting The Grand Project…</body>",
)}`;

let win = null;
let backend = null; // the program started here (null once it stopped, or when another copy serves the page)
let url = null; // the page's address, once the program printed it
let quitting = false;
let logFile = "";

if (!app.requestSingleInstanceLock()) {
	app.quit(); // (a second start: the first one's window comes forward)
} else {
	app.on("second-instance", () => {
		if (win) {
			if (win.isMinimized()) win.restore();
			win.focus();
		}
	});
	app.whenReady().then(start);
	app.on("before-quit", (e) => {
		if (!quitting) {
			e.preventDefault(); // (Cmd+Q, the installer of an update: the program saves first)
			stop();
		}
	});
	app.on("window-all-closed", () => {
		if (quitting) app.quit();
	});
}

function start() {
	const home = app.getPath("userData"); // %APPDATA%/The Grand Project, ~/Library/Application Support/The Grand Project
	fs.mkdirSync(home, { recursive: true });
	logFile = path.join(home, "program.log");
	const log = fs.createWriteStream(logFile, { flags: "w" });

	win = new BrowserWindow({
		width: 1600,
		height: 1000,
		backgroundColor: "#0b0b0f",
		autoHideMenuBar: true,
		title: "The Grand Project",
	});
	win.loadURL(STARTING_PAGE);
	// links away from the page (GitHub's release page, the wiki) open in the browser, not in the app's window
	win.webContents.setWindowOpenHandler(({ url: to }) => {
		if (url && to.startsWith(url)) return { action: "allow" };
		shell.openExternal(to);
		return { action: "deny" };
	});
	win.webContents.on("will-navigate", (e, to) => {
		if (url && !to.startsWith(url) && !to.startsWith("data:")) {
			e.preventDefault();
			shell.openExternal(to);
		}
	});
	win.on("close", (e) => {
		if (!quitting) {
			e.preventDefault();
			stop();
		}
	});

	const { cmd, args, cwd } = backendCommand({
		packaged: app.isPackaged,
		resourcesPath: process.resourcesPath,
		platform: process.platform,
		repo: path.join(__dirname, ".."),
		// (a path given relative to where npm start ran: the program starts in the repo's top)
		python: process.env.GP_PYTHON?.includes(path.sep) ? path.resolve(process.env.GP_PYTHON) : process.env.GP_PYTHON,
	});
	let said = "";
	try {
		backend = spawn(cmd, args, { cwd, env: backendEnv(process.env, home), windowsHide: true });
	} catch (e) {
		fail(`The program couldn't be started: ${e.message}`);
		return;
	}
	backend.on("error", (e) => fail(`The program couldn't be started: ${e.message}`));
	backend.stdout.on("data", (d) => {
		log.write(d);
		if (url) return;
		said += d.toString();
		const found = findUrl(said);
		if (found) {
			url = found;
			win.loadURL(url);
		}
	});
	backend.stderr.on("data", (d) => log.write(d));
	backend.on("exit", (code) => {
		backend = null;
		log.end();
		if (url && handedOver(said)) return; // (another copy serves the page: this one only handed over)
		if (!url && !quitting) fail(`The program stopped before it started (code ${code}).`);
		else finish(); // (stopped from the page, File > Quit the app, or by stop())
	});
	setTimeout(() => {
		if (!url && !quitting) fail("The program didn't start in time.");
	}, START_WAIT_MS);

	if (app.isPackaged && process.platform === "win32") checkForUpdate();
}

/** Ask the program to save and stop (as File > Quit the app does), then quit; it is ended if it doesn't in time. */
function stop() {
	if (quitting) return;
	quitting = true;
	if (win) win.hide();
	if (!url) {
		end();
		return;
	}
	const ask = fetch(`${url}api/quit`, {
		method: "POST",
		headers: { "X-Grand": "1", "Content-Type": "application/json" },
		body: "{}",
	}).catch(() => null);
	if (!backend) {
		ask.finally(finish); // (another copy served the page: asked to stop, nothing of ours to wait for)
		return;
	}
	setTimeout(end, QUIT_WAIT_MS);
}

function end() {
	if (backend) backend.kill();
	finish();
}

function finish() {
	quitting = true;
	app.quit();
}

function fail(why) {
	if (quitting) return;
	quitting = true;
	dialog.showErrorBox("The Grand Project", `${why}\n\nWhat it said: ${logFile}`);
	end();
}

/** Windows: a newer release (its latest.yml on GitHub) downloads in the background and is installed on quit. */
function checkForUpdate() {
	const { autoUpdater } = require("electron-updater");
	autoUpdater.autoInstallOnAppQuit = true;
	autoUpdater.checkForUpdates().catch(() => {}); // (offline, or the release's files not uploaded yet: next start)
}
