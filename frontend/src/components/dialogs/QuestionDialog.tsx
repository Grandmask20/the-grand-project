import { useQueryClient } from "@tanstack/react-query";
import { AppQueryKeys } from "@/api/AppQueryKeys";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import type { AppState } from "@/domain/app/AppState";
import { useAppClient } from "@/hooks/app/UseAppClient";
import { useAppState } from "@/hooks/app/UseAppState";
import { useAppStore } from "@/store/AppStore";

/** A question from the app (a weak match, a crowded folder, a screenshot that could not be lined up). The
 * screenshot it is about is shown on the map meanwhile; the dialog stays off it (top). */
export function QuestionDialog() {
	const app = useAppClient();
	const queryClient = useQueryClient();
	const q = useAppState().data?.questions[0] ?? null;
	const showError = useAppStore((s) => s.showError);

	const answer = (yes: boolean) => {
		if (!q) return;
		queryClient.setQueryData<AppState>(AppQueryKeys.state, (s) =>
			s ? { ...s, questions: s.questions.filter((x) => x.id !== q.id) } : s,
		);
		void app.answer(q.id, yes).catch((e) => {
			showError(e);
			void queryClient.invalidateQueries({ queryKey: AppQueryKeys.state }); // still open: shown again
		});
	};

	return (
		<Dialog open={!!q} onOpenChange={(open) => !open && answer(false)}>
			<DialogContent overlay={false} showCloseButton={false} className="top-4 translate-y-0 sm:max-w-xl">
				<DialogHeader>
					<DialogTitle>Check this screenshot</DialogTitle>
					<DialogDescription className="whitespace-pre-wrap text-foreground">
						{q?.question}
						{q?.preview &&
							(q.preview.agree?.length
								? "\n\n(It is shown and outlined on the map, the maps it agrees with ringed.)"
								: "\n\n(It is shown and outlined on the map.)")}
					</DialogDescription>
				</DialogHeader>
				<DialogFooter>
					<Button variant="outline" onClick={() => answer(false)}>
						No
					</Button>
					<Button onClick={() => answer(true)} autoFocus>
						Yes
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
