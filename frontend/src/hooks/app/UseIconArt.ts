import { useAppState } from "@/hooks/app/UseAppState";

/** The icon pictures' art version (their URLs carry it: asked for again only when a picture can have changed). */
export function useIconArt(): string | undefined {
	return useAppState().data?.map?.sprite.art;
}
