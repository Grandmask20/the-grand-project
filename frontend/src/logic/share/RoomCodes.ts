import { fromB64, ShareCodeError, toB64 } from "./Codes";

/**
 * A room invite (live sharing through the relay): the room's name and the key its messages are sealed with, both
 * made at random by the sharer's page. The relay is told the room only; the key stays in the code, between friends.
 *
 *   GPS1.<room: 16 bytes>.<key: 32 bytes>   (URL-safe base64)
 */

const PREFIX = "GPS1.";
const ROOM_BYTES = 16;
const KEY_BYTES = 32;

export interface RoomInvite {
	/** The room's name, as the relay knows it (22 characters). */
	room: string;
	/** The AES-256 key its messages are sealed with. */
	key: Uint8Array;
	/** The code friends paste. */
	code: string;
}

/** Whether a pasted code is a room invite (else a direct link's). */
export const isRoomCode = (code: string): boolean => code.trim().startsWith(PREFIX);

/** A new room and its invite. */
export function newRoom(): RoomInvite {
	const room = toB64(crypto.getRandomValues(new Uint8Array(ROOM_BYTES)));
	const key = crypto.getRandomValues(new Uint8Array(KEY_BYTES));
	return { room, key, code: `${PREFIX}${room}.${toB64(key)}` };
}

/**
 * A pasted room invite read.
 *
 * @throws ShareCodeError When it isn't one, or was cut short or changed.
 */
export function parseRoom(code: string): RoomInvite {
	const text = code.trim();
	if (!isRoomCode(text)) throw new ShareCodeError("That isn't an invite code.");
	const [room, key64] = text.slice(PREFIX.length).split(".");
	let key: Uint8Array | null = null;
	try {
		key = key64 ? fromB64(key64) : null;
	} catch {
		key = null;
	}
	if (!/^[A-Za-z0-9_-]{22}$/.test(room ?? "") || key?.length !== KEY_BYTES)
		throw new ShareCodeError("That code is cut short or changed: copy it whole again.");
	return { room, key, code: text };
}
