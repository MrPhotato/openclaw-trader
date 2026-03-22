import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#08111f",
        panel: "#0f1b2f",
        ember: "#ff7d45",
        neon: "#71f6d1",
        storm: "#203758",
        signal: "#ffe066",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(113,246,209,0.15), 0 18px 50px rgba(8,17,31,0.45)",
      },
      fontFamily: {
        sans: ["Space Grotesk", "Avenir Next", "Segoe UI", "sans-serif"],
        mono: ["IBM Plex Mono", "JetBrains Mono", "monospace"],
      },
      backgroundImage: {
        "command-grid":
          "radial-gradient(circle at top, rgba(113,246,209,0.12), transparent 28%), linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
      },
      animation: {
        pulseLine: "pulseLine 3s ease-in-out infinite",
      },
      keyframes: {
        pulseLine: {
          "0%, 100%": { opacity: "0.45", transform: "scaleX(0.98)" },
          "50%": { opacity: "1", transform: "scaleX(1)" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
