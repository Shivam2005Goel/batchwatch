/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        flagged: { bg: "#7f1d1d", fg: "#fee2e2", accent: "#ef4444" },
        caution: { bg: "#78350f", fg: "#fef3c7", accent: "#f59e0b" },
        clear: { bg: "#14532d", fg: "#dcfce7", accent: "#22c55e" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
