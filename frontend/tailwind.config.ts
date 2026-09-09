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
          bg: "#070b12",
          panel: "#111a29",
          panelMuted: "#182438",
          border: "#2a3850",
          text: "#e6edf8",
          muted: "#95a5bf",
          accent: "#7cadff",
          good: "#4fd495",
          warn: "#edbf65",
          danger: "#ff7f7f",
        },
      },
      boxShadow: {
        panel: "0 18px 50px rgba(2, 5, 12, 0.55)",
        workspace: "0 40px 120px rgba(0, 0, 0, 0.45)",
      },
      transitionTimingFunction: {
        argus: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
