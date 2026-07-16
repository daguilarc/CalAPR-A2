import fs from "node:fs";
import path from "node:path";

function readManifest(repoRoot: string): Record<string, unknown> {
  const manifestPath = path.join(
    repoRoot,
    "docs",
    "data",
    "releases",
    "2018-2024",
    "manifest.json",
  );
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Missing release manifest: ${manifestPath}`);
  }
  return JSON.parse(fs.readFileSync(manifestPath, "utf-8")) as Record<string, unknown>;
}

export default async function globalSetup(): Promise<void> {
  const repoRoot = path.resolve(__dirname, "..");
  const manifest = readManifest(repoRoot);
  if (manifest.input_profile === "fixture-v1") {
    throw new Error("Playwright requires a non-fixture release manifest (input_profile != fixture-v1).");
  }
}
