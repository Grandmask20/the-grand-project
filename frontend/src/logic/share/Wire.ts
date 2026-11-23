/**
 * Messages over a live link, in frames small enough for any browser's data channel (a whole atlas is megabytes; a
 * channel message past 256 KB isn't safe everywhere): ID:I:N:PART, put back together as they come.
 */

/** Characters per frame. */
export const FRAME = 60_000;

/** A message as frames (`id`: this message's number, unique on its link). */
export function toFrames(msg: unknown, id: number): string[] {
	const json = JSON.stringify(msg);
	const n = Math.max(1, Math.ceil(json.length / FRAME));
	return Array.from({ length: n }, (_, i) => `${id}:${i}:${n}:${json.slice(i * FRAME, (i + 1) * FRAME)}`);
}

/** Puts frames back into messages: a message comes out once all its frames are in (in any order). */
export class Assembler {
	private readonly parts = new Map<number, string[]>();

	/** A frame in: the message it completes, or undefined (more to come, or not a frame). */
	push(frame: string): unknown {
		const m = /^(\d+):(\d+):(\d+):/.exec(frame);
		if (!m) return undefined;
		const [id, i, n] = [Number(m[1]), Number(m[2]), Number(m[3])];
		if (n < 1 || i >= n) return undefined;
		const got = this.parts.get(id) ?? new Array<string>(n);
		got[i] = frame.slice(m[0].length);
		this.parts.set(id, got);
		for (let k = 0; k < n; k++) if (got[k] === undefined) return undefined;
		this.parts.delete(id);
		try {
			return JSON.parse(got.join(""));
		} catch {
			return undefined;
		}
	}
}
