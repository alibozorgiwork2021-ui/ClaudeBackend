import type { Config } from "tailwindcss";

// Dark-minimalist + bento. Node-kind colors mirror claudebackend/core/graphviz.py
// exactly (incl. the PHP purple) so the topology graph and legend stay on-palette.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0e0f13",
        surface: "#16181d",
        "surface-2": "#1c1f26",
        border: "#262a33",
        fg: "#e7e9ee",
        muted: "#8b93a7",
        primary: "#6366f1",
        success: "#22c55e",
        warn: "#f59e0b",
        danger: "#ef4444",
        info: "#38bdf8",
        kind: {
          python: "#4f86c6",
          php: "#777bb3",
          orm: "#7b5cb8",
          dockerfile: "#2496ed",
          config: "#e09f3e",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        bento: "14px",
      },
    },
  },
  plugins: [],
} satisfies Config;
