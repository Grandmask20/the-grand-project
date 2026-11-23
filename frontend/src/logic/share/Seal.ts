import { fromB64, toB64 } from "./Codes";

/**
 * A room's messages sealed in the page (AES-256-GCM) with the key from its invite, so the relay forwards text it can't
 * read or change unnoticed. Each seal has its own random 12-byte IV, written before the sealed text.
 */

/** The room key, ready to seal and open with. */
export function sealKey(raw: Uint8Array): Promise<CryptoKey> {
	return crypto.subtle.importKey("raw", raw as BufferSource, "AES-GCM", false, ["encrypt", "decrypt"]);
}

/** Text sealed: URL-safe base64 of IV + ciphertext. */
export async function seal(key: CryptoKey, text: string): Promise<string> {
	const iv = crypto.getRandomValues(new Uint8Array(12));
	const sealed = new Uint8Array(
		await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(text)),
	);
	const out = new Uint8Array(iv.length + sealed.length);
	out.set(iv);
	out.set(sealed, iv.length);
	return toB64(out);
}

/**
 * Sealed text opened.
 *
 * @throws When it was sealed with another key, or changed on the way.
 */
export async function unseal(key: CryptoKey, sealed: string): Promise<string> {
	const bytes = fromB64(sealed);
	const plain = await crypto.subtle.decrypt(
		{ name: "AES-GCM", iv: bytes.slice(0, 12) },
		key,
		bytes.slice(12) as BufferSource,
	);
	return new TextDecoder().decode(plain);
}
