/** A release's notes (GitHub markdown) as the update box shows them: headings, bullet points and paragraphs, with
 * bold, code and links inside (user: "## 1.3.2 Test" and "- ..." showed as typed). Only the little the notes use: a
 * table or anything else stays plain text. */

/** A piece of a line: plain, bold, code, or a link (http / https only). */
export type NotesSpan = { text: string; bold?: boolean; code?: boolean; href?: string };

/** A block of the notes: a heading, a list of points, or a paragraph (each a list of lines of spans). */
export type NotesBlock =
	| { kind: "heading"; spans: NotesSpan[] }
	| { kind: "list"; items: NotesSpan[][] }
	| { kind: "paragraph"; lines: NotesSpan[][] };

const HEADING = /^#{1,6}\s+(.*?)\s*#*\s*$/;
const POINT = /^\s*[-*+]\s+(.*)$/;
const DIVIDER = /^\s*([-*_])(\s*\1){2,}\s*$/;

/** Split a line into spans: **bold**, `code` and [text](link); a link's address is kept only when http(s). */
export function notesSpans(line: string): NotesSpan[] {
	const out: NotesSpan[] = [];
	const re = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g;
	let at = 0;
	for (let m = re.exec(line); m; m = re.exec(line)) {
		if (m.index > at) out.push({ text: line.slice(at, m.index) });
		if (m[1] !== undefined) out.push({ text: m[1], bold: true });
		else if (m[2] !== undefined) out.push({ text: m[2], code: true });
		else out.push(/^https?:\/\//i.test(m[4]) ? { text: m[3], href: m[4] } : { text: m[3] });
		at = m.index + m[0].length;
	}
	if (at < line.length) out.push({ text: line.slice(at) });
	return out;
}

/** The notes as blocks: a "#" line is a heading, "- " / "* " lines are points, other lines make paragraphs (a blank
 * line ends one); divider lines are left out. */
export function notesBlocks(notes: string): NotesBlock[] {
	const blocks: NotesBlock[] = [];
	for (const raw of notes.replace(/\r\n/g, "\n").split("\n")) {
		const line = raw.trimEnd();
		const last = blocks[blocks.length - 1];
		const h = HEADING.exec(line);
		const p = POINT.exec(line);
		if (!line.trim() || DIVIDER.test(line)) {
			blocks.push({ kind: "paragraph", lines: [] }); // (a break: the next text starts a block of its own)
		} else if (h) {
			blocks.push({ kind: "heading", spans: notesSpans(h[1]) });
		} else if (p) {
			if (last?.kind === "list") last.items.push(notesSpans(p[1]));
			else blocks.push({ kind: "list", items: [notesSpans(p[1])] });
		} else if (last?.kind === "list" && /^\s+\S/.test(raw)) {
			last.items[last.items.length - 1].push({ text: ` ${line.trim()}` }); // (a point going on, indented)
		} else if (last?.kind === "paragraph") {
			last.lines.push(notesSpans(line.trim()));
		} else {
			blocks.push({ kind: "paragraph", lines: [notesSpans(line.trim())] });
		}
	}
	return blocks.filter((b) => b.kind !== "paragraph" || b.lines.length > 0);
}
