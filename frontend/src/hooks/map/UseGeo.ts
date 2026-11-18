import { useMemo } from "react";
import { useAppState } from "@/hooks/app/UseAppState";
import { Geo } from "@/logic/Geo";

/** Atlas units <-> longitude / latitude for the open atlas's map image (null before it is built). */
export function useGeo(): Geo | null {
	const map = useAppState().data?.map ?? null;
	const key = map ? JSON.stringify([map.grid, map.world, map.offset, map.zmax]) : "";
	// biome-ignore lint/correctness/useExhaustiveDependencies: the grid's numbers are the key
	return useMemo(() => (map ? new Geo(map) : null), [key]);
}
