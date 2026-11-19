import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { AtlasPage } from "@/pages/AtlasPage";

export function App() {
	return (
		<ErrorBoundary>
			<AtlasPage />
		</ErrorBoundary>
	);
}
