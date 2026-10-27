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
        "border-subtle": "#22222A",
        "border-focus": "#FAFAFA",
        "text-primary": "#FAFAFA",
        "text-secondary": "#A1A1AA",
        "text-muted": "#52525B",
        "mask-dom-box": "#00F0FF",
        "mask-defect-fill": "rgba(244, 63, 94, 0.35)",
        "triage-amber": "#F59E0B",
        "verified-emerald": "#10B981",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "sans-serif"],
        display: ["var(--font-space-grotesk)", "Space Grotesk", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "JetBrains Mono", "monospace"],
      },
      backgroundImage: {
        "ai-harmony": "linear-gradient(135deg, #38BDF8 0%, #818CF8 50%, #C084FC 100%)",
      },
    },
  },
  plugins: [],
};

export default config;
