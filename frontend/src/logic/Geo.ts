import type { MapInfo } from "@/domain/map/MapInfo";

export type LngLat = [number, number];
export type Point = [number, number];

/**
 * Atlas units <-> the longitude / latitude MapLibre places them at (the app's webmap.tiles.Grid): the map image sits
 * in the middle of a Web Mercator world of `world` px at level zmax, at `offset` px from its corner.
 */
export class Geo {
	readonly x0: number;
	readonly y0: number;
	readonly scale: number;
	readonly world: number;
	readonly offset: number;
	readonly zmax: number;

	constructor(info: Pick<MapInfo, "grid" | "world" | "offset" | "zmax">) {
		this.x0 = info.grid.x0;
		this.y0 = info.grid.y0;
		this.scale = info.grid.scale;
		this.world = info.world;
		this.offset = info.offset;
		this.zmax = info.zmax;
	}

	toLngLat(x: number, y: number): LngLat {
		const wx = (x - this.x0) * this.scale + this.offset;
		const wy = (y - this.y0) * this.scale + this.offset;
		const lng = (wx / this.world) * 360 - 180;
		const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * wy) / this.world))) * 180) / Math.PI;
		return [lng, lat];
	}

	toAtlas(lng: number, lat: number): Point {
		const wx = ((lng + 180) / 360) * this.world;
		const r = (lat * Math.PI) / 180;
		const wy = ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * this.world;
		return [(wx - this.offset) / this.scale + this.x0, (wy - this.offset) / this.scale + this.y0];
	}

	/** Screen px per atlas unit at a map zoom (MapLibre's world is 512 * 2^zoom px). */
	pxPerUnit(zoom: number): number {
		return (this.scale * 512 * 2 ** zoom) / this.world;
	}

	/** The map zoom showing `px` screen px per atlas unit. */
	zoomFor(px: number): number {
		return Math.log2((px * this.world) / (this.scale * 512));
	}

	/** [[west, south], [east, north]] around an atlas box. */
	boundsOf(x0: number, y0: number, x1: number, y1: number): [LngLat, LngLat] {
		const [w, n] = this.toLngLat(x0, y0);
		const [e, s] = this.toLngLat(x1, y1);
		return [
			[w, s],
			[e, n],
		];
	}

	/** The 4 corners of an atlas box as MapLibre image source coordinates (top left, clockwise). */
	corners(box: [number, number, number, number]): [LngLat, LngLat, LngLat, LngLat] {
		const [x0, y0, x1, y1] = box;
		return [this.toLngLat(x0, y0), this.toLngLat(x1, y0), this.toLngLat(x1, y1), this.toLngLat(x0, y1)];
	}

	ring(points: Point[]): LngLat[] {
		const r = points.map(([x, y]) => this.toLngLat(x, y));
		return r.length ? [...r, r[0]] : r;
	}
}
