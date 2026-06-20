/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Light neutral canvas + surfaces.
        // NOTE: the numeric ramp is intentionally inverted vs. a normal scale so
        // existing usage keeps working in light mode: high numbers (800/900/950)
        // are light SURFACES (used as backgrounds), low numbers (50–400) are dark
        // TEXT tones. Flipping these values converts the whole app dark→light
        // without rewriting every `bg-navy-*` / `text-navy-*` utility.
        navy: {
          50: '#0b1220', // darkest — headings / strong text
          100: '#1e293b', // primary body text
          200: '#334155', // strong secondary text
          300: '#475569', // muted text
          400: '#64748b', // faint text
          500: '#94a3b8', // placeholder / faint icons
          600: '#cbd5e1', // medium border
          700: '#e2e8f0', // light border / ring
          800: '#ffffff', // card surface
          900: '#f1f5f9', // primary background
          950: '#ffffff', // deepest panel / sidebar
        },
        // Healthy = teal / green.
        healthy: {
          50: '#ecfdf5',
          100: '#cffae6',
          200: '#9ff0cf',
          300: '#5fdfb2',
          400: '#28c693',
          500: '#10b981', // primary healthy
          600: '#059669',
          700: '#047857',
          800: '#065f46',
          900: '#064e3b',
        },
        // Warning = yellow / orange.
        warning: {
          50: '#fffbeb',
          100: '#fef3c7',
          200: '#fde68a',
          300: '#fcd34d',
          400: '#fbbf24',
          500: '#f59e0b', // primary warning
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
          900: '#7c2d12',
        },
        // Critical = red / pink.
        critical: {
          50: '#fff1f4',
          100: '#ffe1e8',
          200: '#ffc8d6',
          300: '#fda4ba',
          400: '#fb6f93',
          500: '#f43f6e', // primary critical
          600: '#e11d54',
          700: '#be123c',
          800: '#9f1239',
          900: '#881337',
        },
        // Severity tokens (align with backend severity literals).
        sev: {
          critical: '#f43f6e',
          high: '#fb6f93',
          medium: '#f59e0b',
          low: '#10b981',
        },
        // Dimension/heatmap state tokens.
        state: {
          green: '#10b981',
          yellow: '#f59e0b',
          red: '#f43f6e',
          gray: '#94a3b8',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,23,42,0.06), 0 1px 3px rgba(15,23,42,0.10)',
        lift: '0 8px 24px rgba(15,23,42,0.12)',
      },
      borderRadius: {
        xl: '0.875rem',
      },
      keyframes: {
        pulseRing: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.4' },
        },
      },
      animation: {
        pulseRing: 'pulseRing 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
