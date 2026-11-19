import { vi } from "vitest";

/** A map that keeps the sources and layers added to it, in order (the picture components' tests). */
export function fakeMap() {
	const sources = new Map<string, Record<string, unknown>>();
	const layers: { id: string; before?: string; paint: Record<string, unknown> }[] = [];
	const map = {
		_removed: false,
		addSource: vi.fn((id: string, spec: Record<string, unknown>) => {
			sources.set(id, { ...spec, setCoordinates: vi.fn(), play: vi.fn(), pause: vi.fn() });
		}),
		getSource: (id: string) => sources.get(id),
		removeSource: vi.fn((id: string) => sources.delete(id)),
		addLayer: vi.fn((l: { id: string; paint: Record<string, unknown> }, before?: string) => {
			layers.push({ id: l.id, before, paint: { ...l.paint } });
		}),
		getLayer: (id: string) => layers.find((l) => l.id === id),
		removeLayer: vi.fn((id: string) =>
			layers.splice(
				layers.findIndex((l) => l.id === id),
				1,
			),
		),
		setPaintProperty: vi.fn((id: string, k: string, v: unknown) => {
			const l = layers.find((x) => x.id === id);
			if (l) l.paint[k] = v;
		}),
	};
	return { map, sources, layers };
}
