/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Bảng màu công nghiệp Tokinarc — nền thép, accent lửa hàn.
        ink:    { DEFAULT: '#0d1117', 2: '#161b22', 3: '#21262d' },
        line:   '#30363d',
        flame:  { DEFAULT: '#e05c1b', hi: '#f97316' },  // cam lửa hàn
        txt:    { DEFAULT: '#e6edf3', 2: '#8b949e' },
        ok:     '#2ea043', warn: '#d29922', danger: '#f85149',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
