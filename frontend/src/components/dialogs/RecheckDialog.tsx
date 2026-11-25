import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useSettings, useUpdateSettings } from "@/hooks/app/UseSettings";
import { useAtlases } from "@/hooks/atlas/UseAtlases";
import { recheckLines } from "@/logic/Recheck";
import { useAppStore } from "@/store/AppStore";

/** Asks before a Re-check (user: "it should be a prompt, not an instant button"), and says what it will do: since
 * when the atlas was checked, its screenshots by when and on which version they were detected, how many will be
 * detected again and about how long it takes. An atlas that isn't open is opened first. */
export function RecheckDialog() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const json = useAppStore((s) => s.recheckAtlas);
	const close = useAppStore((s) => s.askRecheck);
	const showError = useAppStore((s) => s.showError);
	const atlases = useAtlases();
	const slim = useSettings()?.recheck_slim ?? false;
	const updateSettings = useUpdateSettings();
	const info = useQuery({
		queryKey: ["recheck-info", json],
		queryFn: () => app.recheckInfo(json ?? ""),
		enabled: !!json,
		staleTime: 0,
		gcTime: 0,
	});
	if (!json) return null;
	const atlas = atlases.data?.find((a) => a.json === json);
	const name = atlas?.name ?? json;
	const open = !!atlas?.open;
	const lines = info.data ? recheckLines(info.data) : null;

	const start = () => {
		close(null);
		(open ? app.recheck() : app.recheckAtlas(json))
			.then(() => queryClient.invalidateQueries({ queryKey: AppQueryKeys.state }))
			.catch(showError);
	};

	return (
		<Dialog open onOpenChange={(o) => !o && close(null)}>
			<DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-lg">
				<DialogHeader>
					<DialogTitle>Re-check “{name}”?</DialogTitle>
					<DialogDescription className="text-foreground">
						Screenshots an older detector read are detected again, then the whole atlas is cleaned up, and you choose
						which of the changes to keep.{!open && ` “${name}” is opened first.`}
					</DialogDescription>
				</DialogHeader>
				{info.isPending && <p className="text-muted-foreground text-sm">Reading the atlas…</p>}
				{info.isError && <p className="text-destructive text-sm">Couldn't read it: {String(info.error)}</p>}
				{lines && info.data && (
					<div className="flex flex-col gap-2 text-sm">
						<p>
							<span className="text-muted-foreground">Last re-checked:</span> {lines.last}
						</p>
						<div>
							<p className="text-muted-foreground">Its {info.data.shots} screenshots:</p>
							<ul className="ml-4 list-disc">
								{lines.groups.map((g) => (
									<li key={g.text}>
										{g.text}
										{g.again && <span className="text-amber-500"> · older detector: detected again</span>}
									</li>
								))}
							</ul>
							{info.data.missing > 0 && (
								<p className="text-muted-foreground">
									{info.data.missing} screenshot file(s) are gone: their old detection is used as it is.
								</p>
							)}
						</div>
						<p>{lines.work}</p>
						<p>
							<span className="text-muted-foreground">Takes:</span> {lines.time}
						</p>
						{/* the slim down, packaged with Re-check (user); remembered for every atlas */}
						<div className="flex items-start gap-2">
							<Checkbox
								className="mt-0.5"
								checked={slim}
								id="recheck-slim"
								onCheckedChange={(on) => updateSettings.mutate({ recheck_slim: on === true })}
							/>
							<label htmlFor="recheck-slim">
								<span className="font-semibold">Slim down:</span> also remove the copies of screenshots that show no
								spot of the map{" "}
								{info.data.slim?.clean === false
									? "(needs Fix seams first: only its clean map knows, fog included, which ones those are)"
									: info.data.slim?.count
										? `(${info.data.slim.count} now, about ${info.data.slim.mb} MB)`
										: "(none right now)"}
								. Saves space, but one whose screenshot is gone too can't take a spot back later.
							</label>
						</div>
					</div>
				)}
				<DialogFooter>
					<Button variant="outline" onClick={() => close(null)}>
						Cancel
					</Button>
					<Button autoFocus onClick={start}>
						Re-check
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
