import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAppStore } from "@/store/AppStore";

/** Asks for one line of text (a group, a name, a note). */
export function PromptDialog() {
	const prompt = useAppStore((s) => s.prompt);
	const close = useAppStore((s) => s.ask);
	const [value, setValue] = useState("");

	useEffect(() => setValue(prompt?.value ?? ""), [prompt]);
	if (!prompt) return null;
	const ok = () => {
		close(null);
		prompt.onOk(value.trim());
	};

	return (
		<Dialog open onOpenChange={(open) => !open && close(null)}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>{prompt.title}</DialogTitle>
				</DialogHeader>
				<form
					className="flex flex-col gap-2"
					onSubmit={(e) => {
						e.preventDefault();
						ok();
					}}
				>
					<Label htmlFor="prompt-value">{prompt.label}</Label>
					<Input id="prompt-value" value={value} onChange={(e) => setValue(e.target.value)} list="prompt-options" autoFocus />
					{prompt.options && (
						<datalist id="prompt-options">
							{prompt.options.map((o) => (
								<option key={o} value={o} />
							))}
						</datalist>
					)}
					<DialogFooter>
						<Button type="button" variant="outline" onClick={() => close(null)}>
							Cancel
						</Button>
						<Button type="submit">OK</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
