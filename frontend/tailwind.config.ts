import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        argus: {
          bg: "#0a1220",
          panel: "#0f1a2b",
          panelMuted: "#152338",
          border: "#27354e",
          text: "#dfe8f5",
          muted: "#8ba0c0",
          accent: "#3da9fc",
          good: "#2cc58a",
          warn: "#f5b642",
          danger: "#ff6b6b",
        },
      },
      boxShadow: {
        panel: "0 12px 30px rgba(0, 0, 0, 0.22)",
      },
    },
  },
  plugins: [],
};

export default config;

