import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    base: "/graph/",
    server: {
        port: 5173,
        proxy: {
            "/graph/snapshot": "http://localhost:8808",
            "/graph/status": "http://localhost:8808"
        }
    }
});
