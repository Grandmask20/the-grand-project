import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `npm run dev` serves the page on 5173 and passes /api to the app (python -m grand_project --no-browser).
export default defineConfig({
	plugins: [react(), tailwindcss()],
	resolve: {
		alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
	},
	build: { chunkSizeWarningLimit: 1500 },
	server: {
		port: 5173,
		strictPort: true,
		proxy: {
			"/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
		},
	},
});
