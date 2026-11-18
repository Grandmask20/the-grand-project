/** A model's pick code: its kind (0 map node, 1 landmark) and index, read back from the pick picture's colour. */
export const pickCode = (kind: "node" | "landmark", id: number) => (kind === "node" ? 0 : 1 << 22) + id + 1;

/** What a pick code stands for, or null. */
export function pickItem(code: number): { kind: "node" | "landmark"; id: number } | null {
	if (code <= 0) return null;
	return code >= 1 << 22 ? { kind: "landmark", id: code - (1 << 22) - 1 } : { kind: "node", id: code - 1 };
}
