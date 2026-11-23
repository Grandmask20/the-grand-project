/**
 * Live sharing's two codes, pasted by hand (no server of our own: user): the sharer's invite (their connection
 * offer) and the friend's reply (their answer). Each is a WebRTC session description, squeezed (deflate) and written
 * in URL-safe base64 behind a prefix that says which it is, so the one pasted in the wrong box is told apart.
 */

export type CodeKind = "invite" | "reply";

const PREFIX: Record<CodeKind, string> = { invite: "GPI1", reply: "GPR1" };

/** A code that can't be read: why, in words to show. */
export class ShareCodeError extends Error {}

/** Bytes as URL-safe base64 (no padding). */
export const toB64 = (bytes: Uint8Array): string => {
	let s = "";
	for (const b of bytes) s += String.fromCharCode(b);
	return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
/** URL-safe base64 back to bytes (throws on characters that aren't base64). */
export const fromB64 = (text: string): Uint8Array => {
	const b = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
	return Uint8Array.from(b, (c) => c.charCodeAt(0));
};

const canSqueeze = () =>
	typeof CompressionStream === "function" &&
	typeof DecompressionStream === "function" &&
	typeof ReadableStream === "function";

async function through(bytes: Uint8Array, stream: CompressionStream | DecompressionStream): Promise<Uint8Array> {
	const out = new ReadableStream<Uint8Array>({
		start(c) {
			c.enqueue(bytes);
			c.close();
		},
	})
		.pipeThrough(stream as unknown as ReadableWritablePair<Uint8Array, Uint8Array>)
		.getReader();
	const parts: Uint8Array[] = [];
	for (let r = await out.read(); !r.done; r = await out.read()) parts.push(r.value);
	const all = new Uint8Array(parts.reduce((k, p) => k + p.length, 0));
	let at = 0;
	for (const p of parts) {
		all.set(p, at);
		at += p.length;
	}
	return all;
}

/** A session description as a code to paste: PREFIX.zDATA (deflated) or PREFIX.pDATA (plain, no deflate here). */
export async function packCode(kind: CodeKind, desc: RTCSessionDescriptionInit): Promise<string> {
	const raw = new TextEncoder().encode(JSON.stringify({ t: desc.type, s: desc.sdp }));
	if (canSqueeze()) return `${PREFIX[kind]}.z${toB64(await through(raw, new CompressionStream("deflate-raw")))}`;
	return `${PREFIX[kind]}.p${toB64(raw)}`;
}

/** A code pasted back as a session description; its kind checked (an invite pasted as a reply is said so). */
export async function unpackCode(kind: CodeKind, code: string): Promise<RTCSessionDescriptionInit> {
	const text = code.replace(/\s+/g, "");
	const other: CodeKind = kind === "invite" ? "reply" : "invite";
	if (text.startsWith(`${PREFIX[other]}.`))
		throw new ShareCodeError(
			kind === "invite"
				? "That's a reply code: paste your friend's invite."
				: "That's an invite: paste your friend's reply.",
		);
	if (!text.startsWith(`${PREFIX[kind]}.`))
		throw new ShareCodeError(`That isn't ${kind === "invite" ? "an invite" : "a reply"} code.`);
	const body = text.slice(PREFIX[kind].length + 1);
	try {
		const bytes = fromB64(body.slice(1));
		const raw = body[0] === "z" ? await through(bytes, new DecompressionStream("deflate-raw")) : bytes;
		const { t, s } = JSON.parse(new TextDecoder().decode(raw)) as { t: RTCSdpType; s: string };
		if (typeof s !== "string" || (t !== "offer" && t !== "answer")) throw new Error("no description");
		return { type: t, sdp: s };
	} catch {
		throw new ShareCodeError("That code is cut short or changed: copy it whole again.");
	}
}
