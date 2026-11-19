import type { WaitingShot } from "@/domain/adding/WaitingShot";
import type { WatchState } from "@/domain/adding/WatchState";
import type { Question } from "@/domain/app/Question";
import type { UiSettings } from "@/domain/app/UiSettings";
import type { AtlasSummary } from "@/domain/atlas/AtlasSummary";
import type { MapInfo } from "@/domain/map/MapInfo";

/** GET /api/state: everything the page draws its frame from. */
export interface AppState {
	version: string;
	atlas: AtlasSummary | null;
	model_version: number;
	/** Bumped whenever another atlas is opened, made or closed: what the page shows belongs to one generation. */
	generation?: number;
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
	/** Whose log `log` is: the open atlas's file ("" with none open). */
	log_scope?: string;
	/** The atlas being opened at start (its name): the page shows at once and says so meanwhile. */
	opening?: string | null;
	debug: boolean;
	settings: UiSettings;
	map: MapInfo | null;
}
