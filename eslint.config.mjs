import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  {
    ignores: [
      ".next/**", "node_modules/**", "next-env.d.ts",
      // Python virtualenvs and ML data ship third-party JS (e.g. PyTorch).
      "**/.venv/**", "ml/data/**", "ml/artifacts/**",
    ],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];

export default config;
