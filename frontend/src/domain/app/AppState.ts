import type { AtlasSummary } from "@/domain/atlas/AtlasSummary";
import type { WaitingShot } from "@/domain/adding/WaitingShot";
import type { WatchState } from "@/domain/adding/WatchState";
import type { Question } from "@/domain/app/Question";
import type { UiSettings } from "@/domain/app/UiSettings";
import type { MapInfo } from "@/domain/map/MapInfo";

/** GET /api/state: everything the page draws its frame from. */
export interface AppState {
	version: string;
	atlas: AtlasSummary | null;
	model_version: number;
	terrain_version: number;
	filter_version: number;
	busy: boolean;
	progress: string | null;
	status: string;
	watch: WatchState;
	undo: string[][];
	recent: string[];
	waiting: WaitingShot[];
	seams: boolean;
	questions: Question[];
	log: string[];
	debug: boolean;
	settings: UiSettings;
	map: MapInfo | null;
}
