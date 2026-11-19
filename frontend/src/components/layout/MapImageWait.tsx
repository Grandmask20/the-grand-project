import { PART_QUIET_S, useParts } from "@/hooks/app/UseParts";

/** Before there is a map: the map image being built, how far it is, or why it failed (that only reached the log). */
export function MapImageWait() {
	const part = useParts(true).data?.parts.map_image;
	if (part?.state === "failed")
		return <p className="text-destructive">The map image could not be built: {part.error}</p>;
	return (
		<p>
			Building the map image…
			{part?.state === "building" && part.quiet >= PART_QUIET_S ? ` (no progress for ${Math.round(part.quiet)} s)` : ""}
		</p>
	);
}
