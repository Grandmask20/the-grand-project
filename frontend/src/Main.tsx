import "@/theme/Theme.css";
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/App";
import { createQueryClient } from "@/api/ReactQuery";
import tablet from "@/assets/tablet.png";
import { AppClientProvider } from "@/providers/AppClientProvider";

const queryClient = createQueryClient();

// the browser tab's icon: the in-game tablet (user)
const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
if (icon) icon.href = tablet;

createRoot(document.getElementById("root") as HTMLElement).render(
	<StrictMode>
		<QueryClientProvider client={queryClient}>
			<AppClientProvider>
				<App />
			</AppClientProvider>
		</QueryClientProvider>
	</StrictMode>,
);
