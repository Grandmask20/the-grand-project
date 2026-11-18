import type { Meta } from "@/domain/app/Meta";
import type { Style } from "@/domain/app/Style";

/** A style colour when set ("#rrggbb"), else the default. */
export function styleColour(style: Style, key: string, fallback: string): string {
	const v = style[key];
	return typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v) ? v : fallback;
}

/** City biome tints with the View tab's colours. */
export function cityColours(meta: Meta, style: Style): Record<string, string> {
	const out: Record<string, string> = {};
	for (const [k, c] of Object.entries(meta.colours.city)) out[k] = styleColour(style, `city_col_${k}`, c);
	return out;
}

/** Landmark colours with the View tab's colours. */
export function landmarkColours(meta: Meta, style: Style): Record<string, string> {
	const out: Record<string, string> = {};
	for (const [k, c] of Object.entries(meta.colours.landmark)) out[k] = styleColour(style, `lm_col_${k}`, c);
	return out;
}

/** A colour of a 256-colour spread for a share 0..1. */
export function rampColour(ramp: string[], t: number): string {
	if (!ramp.length) return "#ffffff";
	return ramp[Math.min(ramp.length - 1, Math.max(0, Math.round(t * (ramp.length - 1))))];
}

/** "#rrggbb" + alpha 0..1 as rgba(). */
export function withAlpha(hex: string, a: number): string {
	const n = Number.parseInt(hex.slice(1), 16);
	return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
