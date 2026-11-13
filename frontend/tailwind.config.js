/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Driven by the CSS variables in src/index.css so the whole HUD can be
        // retuned from one place.
        void: "rgb(var(--void) / <alpha-value>)",
        deep: "rgb(var(--deep) / <alpha-value>)",
        panel: "rgb(var(--panel) / <alpha-value>)",
        edge: "rgb(var(--edge) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        holo: "rgb(var(--holo) / <alpha-value>)",
        pulse: "rgb(var(--pulse) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        alarm: "rgb(var(--alarm) / <alpha-value>)",
        ok: "rgb(var(--ok) / <alpha-value>)",
      },
      fontFamily: {
        display: ['"Orbitron"', "ui-sans-serif", "system-ui", "sans-serif"],
        hud: ['"Rajdhani"', "ui-sans-serif", "system-ui", "sans-serif"],
        body: ['"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
      letterSpacing: {
        hud: "0.28em",
        wider2: "0.42em",
      },
      borderRadius: {
        hud: "18px",
      },
      boxShadow: {
        glass: "0 30px 80px -30px rgb(0 0 0 / 0.85), inset 0 1px 0 rgb(255 255 255 / 0.05)",
        holo: "0 0 24px -4px rgb(var(--holo) / 0.45)",
        holoLg: "0 0 60px -12px rgb(var(--holo) / 0.55)",
        pulseGlow: "0 0 40px -10px rgb(var(--pulse) / 0.6)",
        amberGlow: "0 0 60px -12px rgb(var(--warn) / 0.45)",
      },
      transitionTimingFunction: {
        hud: "cubic-bezier(0.22, 1, 0.36, 1)",
      },
      keyframes: {
        "spin-slow": { from: { transform: "rotate(0deg)" }, to: { transform: "rotate(360deg)" } },
        "spin-rev": { from: { transform: "rotate(360deg)" }, to: { transform: "rotate(0deg)" } },
        breathe: {
          "0%, 100%": { transform: "scale(0.965)", opacity: "0.72" },
          "50%": { transform: "scale(1.035)", opacity: "1" },
        },
        ripple: {
          "0%": { transform: "scale(0.72)", opacity: "0.55" },
          "70%": { opacity: "0.12" },
          "100%": { transform: "scale(1.55)", opacity: "0" },
        },
        sweep: {
          "0%": { transform: "translateX(-120%)" },
          "100%": { transform: "translateX(120%)" },
        },
        "msg-in": {
          "0%": { transform: "translate3d(0, 14px, 0)", opacity: "0" },
          "100%": { transform: "translate3d(0, 0, 0)", opacity: "1" },
        },
        "toast-in": {
          "0%": { transform: "translate3d(24px, 0, 0)", opacity: "0" },
          "100%": { transform: "translate3d(0, 0, 0)", opacity: "1" },
        },
        shake: {
          "0%, 100%": { transform: "translate3d(0, 0, 0)" },
          "20%": { transform: "translate3d(-7px, 0, 0)" },
          "40%": { transform: "translate3d(6px, 0, 0)" },
          "60%": { transform: "translate3d(-4px, 0, 0)" },
          "80%": { transform: "translate3d(3px, 0, 0)" },
        },
        caret: { "0%, 49%": { opacity: "1" }, "50%, 100%": { opacity: "0" } },
        wave: { "0%, 100%": { transform: "scaleY(0.28)" }, "50%": { transform: "scaleY(1)" } },
        "fade-up": {
          "0%": { transform: "translate3d(0, 10px, 0)", opacity: "0" },
          "100%": { transform: "translate3d(0, 0, 0)", opacity: "1" },
        },
        blink: { "0%, 100%": { opacity: "0.25" }, "50%": { opacity: "1" } },
      },
      animation: {
        "spin-slow": "spin-slow 26s linear infinite",
        "spin-med": "spin-slow 14s linear infinite",
        "spin-rev": "spin-rev 38s linear infinite",
        "spin-fast": "spin-slow 3.6s linear infinite",
        breathe: "breathe 6s ease-in-out infinite",
        ripple: "ripple 2.8s ease-out infinite",
        sweep: "sweep 5.5s cubic-bezier(0.4, 0, 0.2, 1) infinite",
        "msg-in": "msg-in 320ms cubic-bezier(0.22, 1, 0.36, 1) both",
        "toast-in": "toast-in 260ms cubic-bezier(0.22, 1, 0.36, 1) both",
        shake: "shake 420ms cubic-bezier(0.36, 0.07, 0.19, 0.97)",
        caret: "caret 1.05s step-end infinite",
        wave: "wave 1.15s ease-in-out infinite",
        "fade-up": "fade-up 420ms cubic-bezier(0.22, 1, 0.36, 1) both",
        blink: "blink 2.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
