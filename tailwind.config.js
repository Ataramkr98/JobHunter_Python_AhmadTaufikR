/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/templates/**/*.html"],
  theme: {
    extend: {
      colors: {
        canvas: "#f7f7f4",
        ink: "#172033",
        muted: "#667085",
        line: "#e2e5e1",
        primary: "#3157d5",
        teal: "#0f8a7b",
      },
      fontFamily: {
        sans: ["Plus Jakarta Sans", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
