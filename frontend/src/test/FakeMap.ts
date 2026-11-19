import { vi } from "vitest";
import { fakeGl } from "./FakeGl";

type Listener = (e?: unknown) => void;

/** A layer as the page added it (by hand, or through react-map-gl's <Layer>), with what was set on it since. */
export interface FakeLayer {
	id: string;
	before?: string;
	spec: Record<string, unknown>;
	paint: Record<string, unknown>;
	layout: Record<string, unknown>;
}

/**
 * A MapLibre map for the map's tests: it keeps the sources, layers, pictures, controls and listeners the page gives
 * it, moves its camera when asked (no animation), and fires events on demand (`fire`). The camera is a centre, a zoom,
 * a pitch and a bearing; `project` places a [lng, lat] on a 1000 x 800 screen at 100 px per degree.
 */
export function fakeMap() {
	const listeners = new Map<string, Set<Listener>>();
	const layerListeners = new Map<string, Set<Listener>>(); // "event layer" -> listeners
	const sources = new Map<string, Record<string, unknown>>();
	const layers: FakeLayer[] = [];
	const images = new Map<string, unknown>();
	const controls = new Set<unknown>();
	const container = document.createElement("div");
	const canvasContainer = document.createElement("div");
	const canvas = document.createElement("canvas");
	canvas.className = "maplibregl-canvas";
	canvasContainer.appendChild(canvas);
	container.appendChild(canvasContainer);
	const cam = { lng: 0, lat: 0, zoom: 3, pitch: 0, bearing: 0 };
	const gl = fakeGl();
	let moving = false;

	const fire = (type: string, e: Record<string, unknown> = {}) => {
		for (const fn of [...(listeners.get(type) ?? [])]) fn({ type, target: map, ...e });
	};
	const move = (to: { center?: unknown; zoom?: number; pitch?: number; bearing?: number }) => {
		if (to.center) {
			const c = to.center as [number, number] | { lng: number; lat: number };
			const [lng, lat] = Array.isArray(c) ? c : [c.lng, c.lat];
			Object.assign(cam, { lng, lat });
		}
		if (to.zoom !== undefined) cam.zoom = to.zoom;
		const pitched = to.pitch !== undefined && to.pitch !== cam.pitch;
		if (to.pitch !== undefined) cam.pitch = to.pitch;
		if (to.bearing !== undefined) cam.bearing = to.bearing;
		if (pitched) {
			fire("pitch");
			fire("pitchend");
		}
		fire("move");
		fire("moveend");
	};

	const map = {
		_removed: false,
		style: { _loaded: true },
		on: vi.fn((type: string, a: string | Listener, b?: Listener) => {
			if (typeof a === "string" && b) {
				const key = `${type} ${a}`;
				layerListeners.set(key, (layerListeners.get(key) ?? new Set()).add(b));
			} else listeners.set(type, (listeners.get(type) ?? new Set()).add(a as Listener));
			return map;
		}),
		off: vi.fn((type: string, a: string | Listener, b?: Listener) => {
			if (typeof a === "string" && b) layerListeners.get(`${type} ${a}`)?.delete(b);
			else listeners.get(type)?.delete(a as Listener);
			return map;
		}),
		once: vi.fn((type: string, fn: Listener) => {
			const once = (e?: unknown) => {
				listeners.get(type)?.delete(once);
				fn(e);
			};
			listeners.set(type, (listeners.get(type) ?? new Set()).add(once));
			return map;
		}),
		getCanvas: () => canvas,
		getCanvasContainer: () => canvasContainer,
		getContainer: () => container,
		getCenter: () => ({ lng: cam.lng, lat: cam.lat }),
		getZoom: () => cam.zoom,
		getPitch: () => cam.pitch,
		getBearing: () => cam.bearing,
		getMaxZoom: () => 12,
		isMoving: () => moving,
		isStyleLoaded: () => true,
		isSourceLoaded: () => true,
		loaded: () => true,
		project: (ll: [number, number] | { lng: number; lat: number }) => {
			const [lng, lat] = Array.isArray(ll) ? ll : [ll.lng, ll.lat];
			return { x: 500 + (lng - cam.lng) * 100, y: 400 - (lat - cam.lat) * 100 };
		},
		unproject: ([x, y]: [number, number]) => ({ lng: cam.lng + (x - 500) / 100, lat: cam.lat - (y - 400) / 100 }),
		jumpTo: vi.fn(move),
		easeTo: vi.fn(move),
		flyTo: vi.fn(move),
		panBy: vi.fn(([dx, dy]: [number, number]) => move({ center: [cam.lng + dx / 100, cam.lat - dy / 100] })),
		fitBounds: vi.fn((b: [[number, number], [number, number]]) =>
			move({ center: [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2] }),
		),
		triggerRepaint: vi.fn(),
		addSource: vi.fn((id: string, spec: Record<string, unknown>) => {
			sources.set(id, { ...spec, setCoordinates: vi.fn(), play: vi.fn(), pause: vi.fn(), setData: vi.fn() });
		}),
		getSource: (id: string) => sources.get(id),
		removeSource: vi.fn((id: string) => sources.delete(id)),
		addLayer: vi.fn((spec: Record<string, unknown> & { id: string }, before?: string) => {
			const layer = {
				id: spec.id,
				before,
				spec,
				paint: { ...(spec.paint as object) },
				layout: { ...(spec.layout as object) },
			};
			// as MapLibre: right under the layer it is put before (on top without one, or when that one isn't there)
			const at = before === undefined ? -1 : layers.findIndex((l) => l.id === before);
			if (at < 0) layers.push(layer);
			else layers.splice(at, 0, layer);
			const impl = spec as { onAdd?: (m: unknown, gl: unknown) => void };
			impl.onAdd?.(map, gl.gl); // a custom (3D) layer
		}),
		getLayer: (id: string) => {
			const l = layers.find((x) => x.id === id);
			return l ? { id, implementation: l.spec } : undefined;
		},
		removeLayer: vi.fn((id: string) => {
			const i = layers.findIndex((l) => l.id === id);
			if (i < 0) return;
			const impl = layers[i].spec as { onRemove?: (m: unknown, gl: unknown) => void };
			impl.onRemove?.(map, gl.gl);
			layers.splice(i, 1);
		}),
		getLayoutProperty: (id: string, k: string) => layers.find((l) => l.id === id)?.layout[k],
		setLayoutProperty: vi.fn((id: string, k: string, v: unknown) => {
			const l = layers.find((x) => x.id === id);
			if (l) l.layout[k] = v;
		}),
		setPaintProperty: vi.fn((id: string, k: string, v: unknown) => {
			const l = layers.find((x) => x.id === id);
			if (l) l.paint[k] = v;
		}),
		getStyle: () => ({ layers: layers.map((l) => ({ id: l.id, ...l.spec, layout: l.layout })) }),
		queryRenderedFeatures: vi.fn((): unknown[] => []),
		hasImage: (id: string) => images.has(id),
		addImage: vi.fn((id: string, img: unknown) => images.set(id, img)),
		updateImage: vi.fn((id: string, img: unknown) => images.set(id, img)),
		removeImage: vi.fn((id: string) => images.delete(id)),
		loadImage: vi.fn(async (_url: string) => ({ data: { width: 1, height: 1, data: new Uint8Array(4) } })),
		addControl: vi.fn((c: { onAdd?: (m: unknown) => HTMLElement }) => {
			controls.add(c);
			const el = c.onAdd?.(map);
			if (el) container.appendChild(el);
			return map;
		}),
		removeControl: vi.fn((c: { onRemove?: () => void }) => {
			controls.delete(c);
			c.onRemove?.();
			return map;
		}),
		hasControl: (c: unknown) => controls.has(c),
	};

	return {
		map,
		sources,
		layers,
		images,
		controls,
		cam,
		gl,
		container,
		/** Fire a map event (with fields such as lngLat, point, originalEvent). */
		fire,
		/** Fire a layer's event (mouseenter / mouseleave on "maps"). */
		fireOn: (type: string, layer: string, e: Record<string, unknown> = {}) => {
			for (const fn of [...(layerListeners.get(`${type} ${layer}`) ?? [])]) fn({ type, ...e });
		},
		setMoving: (on: boolean) => {
			moving = on;
		},
		/** The layer ids, bottom to top. */
		layerIds: () => layers.map((l) => l.id),
		/** The listeners of an event. */
		count: (type: string) => listeners.get(type)?.size ?? 0,
	};
}

export type FakeMap = ReturnType<typeof fakeMap>;
