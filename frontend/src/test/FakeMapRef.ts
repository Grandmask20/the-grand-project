import type { FakeMap } from "./FakeMap";

/** The fake map a mocked react-map-gl Map hands its onLoad (a test sets it). */
export const current: { map: FakeMap | null } = { map: null };
