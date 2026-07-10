import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const projectRoot = resolve(__dirname, "..");

describe("Tailwind pipeline configuration", () => {
  it("includes a Tailwind config that scans the app and src directories", () => {
    const configPath = resolve(projectRoot, "tailwind.config.ts");

    expect(existsSync(configPath)).toBe(true);

    const config = readFileSync(configPath, "utf8");

    expect(config).toContain("./app/**/*.{ts,tsx}");
    expect(config).toContain("./src/**/*.{ts,tsx}");
  });

  it("includes a PostCSS config that enables the Tailwind plugin", () => {
    const configPath = resolve(projectRoot, "postcss.config.js");

    expect(existsSync(configPath)).toBe(true);

    const config = readFileSync(configPath, "utf8");

    expect(config).toContain("tailwindcss");
  });
});
