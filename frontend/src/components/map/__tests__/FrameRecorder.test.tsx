import { act } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FrameRecorder } from "@/components/map/FrameRecorder";
import { frameLog } from "@/logic/FrameLog";
import { useAppStore } from "@/store/AppStore";
import { renderOnMap } from "@/test/RenderOnMap";

vi.mock("react-map-gl/maplibre", () => import("@/test/ReactMapGlMock"));

describe("FrameRecorder", () => {
	it("notes every frame the map draws while the frame log is on", () => {
		const frame = vi.spyOn(frameLog, "frame");
		const { fm } = renderOnMap(<FrameRecorder />);
		act(() => fm.fire("render"));
		expect(frame).not.toHaveBeenCalled();
		act(() => useAppStore.setState({ frameLog: true }));
		fm.setMoving(true);
		act(() => fm.fire("render"));
		expect(frame).toHaveBeenCalledWith(3, "moving");
		act(() => useAppStore.setState({ frameLog: false }));
		expect(fm.count("render")).toBe(0);
	});
});
