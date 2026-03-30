import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const reactRoot = resolve(import.meta.dirname, "..");
const distDir = resolve(reactRoot, "dist");
const targetDir = resolve(reactRoot, "..", "psh-fastapi", "static");

if (!existsSync(distDir)) {
  throw new Error("dist directory not found. Run npm run build first.");
}

rmSync(targetDir, { recursive: true, force: true });
mkdirSync(targetDir, { recursive: true });
cpSync(distDir, targetDir, { recursive: true });

console.log(`Copied ${distDir} -> ${targetDir}`);
