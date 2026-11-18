/**
 * The folders from the top down to `path` (each a full path), for the file browser's path bar and folder tree. The
 * top is the drive ("C:\"), "/" or, for a Windows network path, the share ("\\server\share\"): split as a plain path,
 * a network path's top came out as "\" and every folder under it was wrong (CodeRabbit).
 */
export function ancestors(path: string): { name: string; path: string }[] {
	if (!path || path === "drives") return [];
	const sep = path.includes("\\") ? "\\" : "/";
	let root: string;
	let rest: string;
	const share = sep === "\\" ? /^\\\\[^\\]+\\[^\\]+\\?/.exec(path) : null;
	if (share) {
		root = share[0].endsWith("\\") ? share[0] : `${share[0]}\\`;
		rest = path.slice(share[0].length);
	} else {
		const i = path.indexOf(sep);
		root = i < 0 ? `${path}${sep}` : path.slice(0, i + 1);
		rest = i < 0 ? "" : path.slice(i + 1);
	}
	const out = [{ name: root, path: root }];
	let acc = root;
	for (const part of rest.split(sep).filter(Boolean)) {
		acc = acc.endsWith(sep) ? `${acc}${part}` : `${acc}${sep}${part}`;
		out.push({ name: part, path: acc });
	}
	return out;
}
