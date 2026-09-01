/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        /* Command-center surfaces: near-black, layered by elevation rather than
           by gradient. */
        ink: {
          950: '#07090d',
          900: '#0b0e14',
          850: '#10141c',
          800: '#151a24',
          750: '#1b2130',
          700: '#232b3c',
          600: '#2f394e',
        },
        slate: {
          450: '#8b98ad',
        },
        /* Revenue states. Money recovered is green, at risk is amber,
           stopped is slate, escalated is violet, blocked is red. */
        recovered: {
          DEFAULT: '#22c55e',
          soft: '#0f2a1b',
          ring: '#16a34a',
        },
        atrisk: {
          DEFAULT: '#f59e0b',
          soft: '#2a1f0c',
          ring: '#d97706',
        },
        escalated: {
          DEFAULT: '#a78bfa',
          soft: '#211c33',
          ring: '#8b5cf6',
        },
        blocked: {
          DEFAULT: '#f87171',
          soft: '#2a1416',
          ring: '#ef4444',
        },
        accent: {
          DEFAULT: '#38bdf8',
          soft: '#0c2231',
          ring: '#0ea5e9',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        'metric-lg': ['2.5rem', { lineHeight: '1.05', letterSpacing: '-0.02em' }],
        'metric': ['1.875rem', { lineHeight: '1.1', letterSpacing: '-0.015em' }],
        'metric-sm': ['1.375rem', { lineHeight: '1.15', letterSpacing: '-0.01em' }],
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.045)',
        'card-hover': '0 6px 24px -8px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.08)',
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-ring': {
          '0%': { boxShadow: '0 0 0 0 rgba(56,189,248,0.35)' },
          '70%': { boxShadow: '0 0 0 8px rgba(56,189,248,0)' },
          '100%': { boxShadow: '0 0 0 0 rgba(56,189,248,0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 260ms cubic-bezier(0.22,1,0.36,1) both',
        'pulse-ring': 'pulse-ring 1.6s ease-out infinite',
        shimmer: 'shimmer 1.4s infinite',
      },
    },
  },
  plugins: [],
};
