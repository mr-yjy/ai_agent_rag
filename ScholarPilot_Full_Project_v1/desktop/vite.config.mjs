import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const rendererRoot = fileURLToPath(
  new URL("./renderer/", import.meta.url),
);

export default defineConfig({
  root: rendererRoot,
  base: "./",
  plugins: [react()],
  resolve: {
    alias: {
      "@": projectRoot,
    },
  },
  build: {
    outDir: fileURLToPath(
      new URL("../desktop-dist/renderer/", import.meta.url),
    ),
    emptyOutDir: true,
    sourcemap: false,
  },
});
