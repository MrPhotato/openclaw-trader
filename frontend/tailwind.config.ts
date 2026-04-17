import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#08111f",
        "ink-2": "#0b1628",
        "ink-3": "#0e1c33",
        graphite: "#14233b",
        panel: "#0f1b2f",
        ember: "#ff7d45",
        "ember-soft": "rgba(255,125,69,0.16)",
        neon: "#71f6d1",
        "neon-soft": "rgba(113,246,209,0.14)",
        storm: "#203758",
        signal: "#ffe066",
        "border-subtle": "rgba(255,255,255,0.06)",
        "border-strong": "rgba(255,255,255,0.12)",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(113,246,209,0.15), 0 18px 50px rgba(8,17,31,0.45)",
        "elev-1": "0 1px 0 rgba(255,255,255,0.04) inset, 0 10px 30px rgba(2,6,23,0.35)",
        "elev-2": "0 1px 0 rgba(255,255,255,0.05) inset, 0 20px 60px rgba(2,6,23,0.55)",
        "rail-glow": "inset 2px 0 0 0 rgba(113,246,209,0.85), 0 0 24px rgba(113,246,209,0.18)",
        "hero-ring": "0 0 0 1px rgba(113,246,209,0.28), 0 24px 60px rgba(2,6,23,0.55)",
      },
      fontFamily: {
        sans: ["Space Grotesk", "Avenir Next", "Segoe UI", "sans-serif"],
        mono: ["IBM Plex Mono", "JetBrains Mono", "monospace"],
      },
      backgroundImage: {
        "command-grid":
          "radial-gradient(circle at top, rgba(113,246,209,0.12), transparent 28%), linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
        "soft-grid":
          "linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)",
        "hairline-ring":
          "linear-gradient(135deg, rgba(113,246,209,0.35), rgba(255,125,69,0.2) 55%, rgba(255,255,255,0) 95%)",
        "brand-aurora":
          "radial-gradient(120% 120% at 10% 0%, rgba(113,246,209,0.18), transparent 55%), radial-gradient(120% 120% at 100% 100%, rgba(255,125,69,0.12), transparent 60%)",
      },
      animation: {
        pulseLine: "pulseLine 3s ease-in-out infinite",
        shimmer: "shimmer 1.8s linear infinite",
        pulseDot: "pulseDot 2.2s ease-in-out infinite",
      },
      keyframes: {
        pulseLine: {
          "0%, 100%": { opacity: "0.45", transform: "scaleX(0.98)" },
          "50%": { opacity: "1", transform: "scaleX(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: "400px 0" },
        },
        pulseDot: {
          "0%, 100%": { opacity: "0.75", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.2)" },
        },
      },
    },
  },
  plugins: [],
} satisfies Config;
