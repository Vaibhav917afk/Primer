import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#151B24",
          dim: "#5B6B7C",
          faint: "#8B99A8",
        },
        paper: "#FAFAF8",
        panel: {
          DEFAULT: "#FFFFFF",
          border: "#E4E1D9",
        },
        gold: {
          DEFAULT: "#A6742C",
          soft: "#F4E9D8",
        },
        teal: {
          DEFAULT: "#2F6B62",
          soft: "#E1EEEC",
        },
        brick: {
          DEFAULT: "#A23B28",
          soft: "#F5E3DE",
        },
      },
      fontFamily: {
        serif: ["var(--font-plex-serif)", "serif"],
        sans: ["var(--font-plex-sans)", "sans-serif"],
        mono: ["var(--font-plex-mono)", "monospace"],
      },
      borderRadius: {
        lg: "0.625rem",
        md: "0.4rem",
        sm: "0.25rem",
      },
      maxWidth: {
        prose: "68ch",
      },
    },
  },
  plugins: [],
};

export default config;
