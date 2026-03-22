import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    server: {
        port: 4173,
        proxy: {
            "/api": "http://127.0.0.1:8788",
        },
    },
    test: {
        globals: true,
        environment: "jsdom",
        setupFiles: "./src/test-setup.ts",
    },
});
