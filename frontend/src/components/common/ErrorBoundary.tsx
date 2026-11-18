import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

/** A crash in the page shows what went wrong and a reload button, not a black page (user). */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
	state: { error: Error | null } = { error: null };

	static getDerivedStateFromError(error: Error) {
		return { error };
	}

	componentDidCatch(error: Error) {
		console.error("page crashed:", error);
	}

	render() {
		if (!this.state.error) return this.props.children;
		return (
			<div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
				<h1 className="text-lg font-semibold text-gold">Something went wrong on this page</h1>
				<p className="max-w-xl font-mono text-xs break-all text-muted-foreground">{String(this.state.error.message)}</p>
				<p className="text-muted-foreground">The app itself is still running: reload to carry on.</p>
				<Button onClick={() => window.location.reload()}>Reload</Button>
			</div>
		);
	}
}
