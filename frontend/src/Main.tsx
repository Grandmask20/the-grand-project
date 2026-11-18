import "@/theme/Theme.css";
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/App";
import { createQueryClient } from "@/api/ReactQuery";
import { AppClientProvider } from "@/providers/AppClientProvider";

const queryClient = createQueryClient();

createRoot(document.getElementById("root") as HTMLElement).render(
	<StrictMode>
		<QueryClientProvider client={queryClient}>
			<AppClientProvider>
				<App />
			</AppClientProvider>
		</QueryClientProvider>
	</StrictMode>,
);
