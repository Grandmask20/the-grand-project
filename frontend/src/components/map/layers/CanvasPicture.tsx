import type { CanvasSource } from "maplibre-gl";
import { useEffect, useState } from "react";
import { mapAlive, useMapLibre } from "@/hooks/map/UseMapLibre";
import { type LayerId, slotOf } from "@/logic/map/LayerOrder";
import type { Corners } from "./PictureLayer";

interface Props {
	/** The layer and its source (in LAYER_ORDER). */
	id: LayerId;
	width: number;
	height: number;
	corners: Corners;
	/** Draws the picture: called again whenever it changes. */
	draw: (ctx: CanvasRenderingContext2D, width: number, height: number) => void;
	opacity?: number;
	resampling?: "linear" | "nearest";
}

/**
 * A picture the page draws, over 4 corners of the map (Colour by, the timelapse's fog). A still canvas source, put on
 * the map again only when drawn anew: animated, MapLibre read it every frame, also while paused. Shown while mounted.
 */
export function CanvasPicture({ id, width, height, corners, draw, opacity = 1, resampling }: Props) {
	const map = useMapLibre();
	const [canvas, setCanvas] = useState<HTMLCanvasElement | null>(null);
	const place = JSON.stringify(corners); // (a new array with every render)

	// a new canvas for another size or place
	// biome-ignore lint/correctness/useExhaustiveDependencies: opacity is set below, not made again for it
	useEffect(() => {
		const c = document.createElement("canvas");
		c.width = width;
		c.height = height;
		map.addSource(id, { type: "canvas", canvas: c, coordinates: JSON.parse(place), animate: false });
		map.addLayer(
			{
				id,
				type: "raster",
				source: id,
				paint: {
					"raster-fade-duration": 0,
					"raster-opacity": opacity,
					...(resampling ? { "raster-resampling": resampling } : {}),
				},
			},
			slotOf(id),
		);
		setCanvas(c);
		return () => {
			setCanvas(null);
			if (!mapAlive(map)) return;
			if (map.getLayer(id)) map.removeLayer(id);
			if (map.getSource(id)) map.removeSource(id);
		};
	}, [map, id, width, height, place, resampling]);

	useEffect(() => {
		if (map.getLayer(id)) map.setPaintProperty(id, "raster-opacity", opacity);
	}, [map, id, opacity]);

	// the drawing: again with every new draw (its inputs changed), then read by the map for one frame
	useEffect(() => {
		const ctx = canvas?.getContext("2d");
		if (!canvas || !ctx) return;
		draw(ctx, canvas.width, canvas.height);
		const src = map.getSource(id) as CanvasSource | undefined;
		if (!src) return;
		src.play();
		const frame = requestAnimationFrame(() => src.pause());
		return () => cancelAnimationFrame(frame);
	}, [map, id, draw, canvas]);

	return null;
}
