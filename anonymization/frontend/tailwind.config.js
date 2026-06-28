/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#FFFFFF',
        'bg-card': '#F1F5F9',
        'bg-surface': '#F8FAFC',
        accent: '#3B82C8',
        'accent-dim': '#64A3DE',
        border: '#E2E8F0',
        'text-primary': '#1E293B',
        'text-dim': '#475569',
        'text-muted': '#94A3B8',
        'hl-name': '#FDE68A',
        'hl-phone': '#A7F3D0',
        'hl-email': '#BFDBFE',
        'hl-brand': '#FECACA',
        'hl-other': '#E9D5FF',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
