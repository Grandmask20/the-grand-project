import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config";

export default mergeConfig(
	viteConfig,
	defineConfig({
		test: {
			environment: "jsdom",
			setupFiles: ["./src/test/Setup.ts"],
			include: ["src/**/*.test.{ts,tsx}"], // e2e/ is Playwright's (npm run e2e)
			coverage: {
				provider: "v8",
				include: ["src/**/*.{ts,tsx}"],
				// shadcn/ui's own parts, the test helpers, the entry point and the types (no code)
				exclude: [
					"src/components/ui/**",
					"src/test/**",
					"src/**/__tests__/**",
					"src/Main.tsx",
					"src/domain/**",
					"src/**/*.d.ts",
				],
				reporter: ["text-summary", "html", "json-summary", "lcov"],
				reportsDirectory: "coverage",
			},
		},
	}),
);
