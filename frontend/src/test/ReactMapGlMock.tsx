import { Children, cloneElement, isValidElement, type ReactNode, useEffect, useState } from "react";
import type { FakeMap } from "./FakeMap";

/**
 * react-map-gl for the map's tests (vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"))): its
 * components put their sources and layers on the test's fake map (setMap) the way react-map-gl does, so a test
 * reads what a component drew from the fake map's sources and layers.
 */
let current: FakeMap | null = null;

/** The fake map the components draw on. */
export function setMap(m: FakeMap | null): void {
	current = m;
}

const fm = (): FakeMap => {
	if (!current) throw new Error("setMap(fakeMap()) first");
	return current;
};

export function useMap() {
	return { current: { getMap: () => fm().map } };
}

export function Source({ id, children, ...spec }: { id: string; children?: ReactNode } & Record<string, unknown>) {
	const m = fm();
	const had = m.sources.get(id);
	if (!had) m.map.addSource(id, spec);
	else Object.assign(had, spec); // (the data, tiles or picture it shows now)
	useEffect(
		() => () => {
			m.sources.delete(id);
		},
		[m, id],
	);
	return Children.map(children, (c) => (isValidElement(c) ? cloneElement(c, { source: id } as object) : c));
}

export function Layer({ beforeId, ...spec }: { id: string; beforeId?: string } & Record<string, unknown>) {
	const m = fm();
	const had = m.layers.find((l) => l.id === spec.id);
	if (!had) m.map.addLayer(spec as { id: string }, beforeId);
	else {
		had.spec = spec;
		had.paint = { ...(spec.paint as object) };
		had.layout = { ...(spec.layout as object) };
	}
	useEffect(
		() => () => {
			const i = m.layers.findIndex((l) => l.id === spec.id);
			if (i >= 0) m.layers.splice(i, 1);
		},
		[m, spec.id],
	);
	return null;
}

export function Marker({
	longitude,
	latitude,
	children,
}: {
	longitude: number;
	latitude: number;
	children?: ReactNode;
}) {
	return (
		<div data-testid="marker" data-lnglat={`${longitude},${latitude}`}>
			{children}
		</div>
	);
}

export function useControl<T>(make: () => T, _opts?: unknown): T {
	const m = fm();
	const [ctrl] = useState(make);
	useEffect(() => {
		m.map.addControl(ctrl as never);
		return () => {
			m.map.removeControl(ctrl as never);
		};
	}, [m, ctrl]);
	return ctrl;
}

let failure: Record<string, unknown> | null = null;

/** The next map fails as MapLibre would (`error` with or without a sourceId) instead of loading; null: it loads. */
export function failWith(e: Record<string, unknown> | null): void {
	failure = e;
}

/** The map: loaded at once (onLoad with the fake map), its children drawn on it; or its error (failWith). */
function MapView({
	children,
	onLoad,
	onError,
}: {
	children?: ReactNode;
	onLoad?: (e: { target: unknown }) => void;
	onError?: (e: unknown) => void;
}) {
	const m = fm();
	useEffect(() => {
		if (failure) onError?.(failure);
		if (!failure || failure.sourceId) onLoad?.({ target: m.map });
	}, [m, onLoad, onError]);
	return <div data-testid="map-gl">{children}</div>;
}

export function NavigationControl() {
	return null;
}

export function FullscreenControl() {
	return null;
}

// react-map-gl's name for it
export { MapView as Map };
