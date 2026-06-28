/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#FFFFFF',
        'bg-card': '#F1F5F9',
        'bg-card-hover': '#E2E8F0',
        'bg-surface': '#F8FAFC',
        accent: '#3B82C8',
        'accent-dim': '#64A3DE',
        border: '#E2E8F0',
        'border-light': '#CBD5E1',
        'text-primary': '#1E293B',
        'text-dim': '#475569',
        'text-muted': '#94A3B8',
        graphite: '#E2E8F0',
        pearl: '#1E293B',
        smoke: '#475569',
        platinum: '#3B82C8',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
