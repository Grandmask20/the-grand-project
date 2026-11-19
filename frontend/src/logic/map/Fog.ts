import type { ReplayFog } from "@/domain/replay/ReplayPlan";
import { fogCover, fogStep } from "@/logic/Replay";

export type FogField = NonNullable<ReplayFog["field"]>;

/** The area sweep's soft edge, as a share of the whole replay (the app's REPLAY_AREA_SOFT). */
export const FOG_SOFT = 0.02;

/** The fog field's cells: the step each spot is revealed at (65535: no ground there), from its base64. */
export function fogCells(field: FogField): Uint16Array {
	const bin = atob(field.data);
	const out = new Uint16Array(field.w * field.h);
	for (let i = 0; i < out.length; i++) out[i] = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8);
	return out;
}

/**
 * Paint the fog at the replay's position into RGBA pixels: black, as opaque as the spot is still hidden (soft-edged
 * when revealing by area); no ground, nothing to hide.
 */
export function paintFog(
	px: Uint8ClampedArray,
	cells: Uint16Array,
	top: number,
	pos: number,
	area: boolean,
	nSteps: number,
): void {
	const soft = Math.max(1e-6, FOG_SOFT * nSteps); // the sweep's edge fades over this many steps
	for (let i = 0; i < cells.length; i++) {
		const v = cells[i];
		if (v === 65535) continue;
		px[4 * i + 3] = Math.round(fogCover(fogStep(v, top, area), pos, area, soft) * 255);
	}
}
