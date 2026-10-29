import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#0A0A0C",
        surface: "#111115",
        elevated: "#18181E",
        "surface-subtle": "#0B0C10",
        "surface-base": "#111115",
        "surface-elevated": "#18181E",
        "surface-overlay": "#1E202C",
        "border-subtle": "#22222A",
        "border-strong": "#2D3340",
        "border-focus": "#FAFAFA",
        "border-laser": "#00F2FE",
        "text-primary": "#FAFAFA",
        "text-secondary": "#A1A1AA",
        "text-muted": "#52525B",
        "mask-dom-box": "#00F0FF",
        "mask-defect-fill": "rgba(244, 63, 94, 0.35)",
        "laser-cyan": "#00F2FE",
        "defect-crimson": "#FF2E55",
        "defect-crimson-fill": "rgba(255, 46, 85, 0.28)",
        "triage-amber": "#F59E0B",
        "verified-emerald": "#10B981",
        "verified-emerald-fill": "rgba(16, 185, 129, 0.15)",
        "neural-pulse": "#38BDF8",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "sans-serif"],
        display: ["var(--font-space-grotesk)", "Space Grotesk", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "JetBrains Mono", "monospace"],
      },
      backgroundImage: {
        "ai-harmony": "linear-gradient(135deg, #38BDF8 0%, #818CF8 50%, #C084FC 100%)",
        "visor-laser": "linear-gradient(90deg, transparent, #00F2FE 50%, transparent)",
        "grid-pattern": "linear-gradient(to right, rgba(255,255,255,0.03) 1px, transparent 1px), linear-gradient(to bottom, rgba(255,255,255,0.03) 1px, transparent 1px)",
        "optical-blueprint": "linear-gradient(to right, rgba(0, 242, 254, 0.04) 1px, transparent 1px), linear-gradient(to bottom, rgba(0, 242, 254, 0.04) 1px, transparent 1px)",
      },
      boxShadow: {
        "glow-cyan": "0 0 24px -4px rgba(0, 242, 254, 0.35)",
        "glow-emerald": "0 0 24px -4px rgba(16, 185, 129, 0.35)",
        "glow-rose": "0 0 24px -4px rgba(255, 46, 85, 0.35)",
        "laser-line": "0 0 12px 1px #00F2FE",
      },
      animation: {
        "laser-sweep": "visor-laser-sweep 3.5s cubic-bezier(0.4, 0, 0.2, 1) infinite",
        "radar-ping": "visor-radar-ping 2s cubic-bezier(0, 0, 0.2, 1) infinite",
        "ambient-pulse": "ambient-pulse 8s ease-in-out infinite",
        "border-beam": "border-glow-beam 4s linear infinite",
      },
      keyframes: {
        "visor-laser-sweep": {
          "0%": { transform: "translateY(-100%)", opacity: "0" },
          "15%": { opacity: "0.9" },
          "85%": { opacity: "0.9" },
          "100%": { transform: "translateY(550%)", opacity: "0" },
        },
        "visor-radar-ping": {
          "0%": { transform: "scale(0.9)", opacity: "0.8" },
          "100%": { transform: "scale(2.2)", opacity: "0" },
        },
        "border-glow-beam": {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        "ambient-pulse": {
          "0%, 100%": { opacity: "0.06", transform: "scale(1)" },
          "50%": { opacity: "0.14", transform: "scale(1.04)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
