import js from "@eslint/js";
import tseslint from "typescript-eslint";
import noUnnecessaryHookToDom from "./src/lib/eslint-rules/no-unnecessary-hook-to-dom.mjs";

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  // Global ignores — no reason to lint vendored or generated files
  { ignores: [".next/*", "node_modules/*", "NUL"] },

  // Base recommended rules (applied to all .ts/.tsx files)
  js.configs.recommended,
  ...tseslint.configs.recommended,

  // Custom rule plugin — registered as `mitems/` namespace
  {
    plugins: {
      mitems: {
        rules: {
          "no-unnecessary-hook-to-dom": noUnnecessaryHookToDom,
        },
      },
    },
  },

  // Default rules for ALL files — strict checking everywhere
  {
    rules: {
      "mitems/no-unnecessary-hook-to-dom": "warn",
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
    },
  },

  // Intelligence panels — relaxed rules for dynamically-typed Python data
  {
    files: ["src/components/intelligence/**"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": "warn",
    },
  },
);
