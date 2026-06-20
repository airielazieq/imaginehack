/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Dark navy base canvas + surfaces.
        navy: {
          50: '#eef2f9',
          100: '#d6def0',
          200: '#aebfe0',
          300: '#7e98cc',
          400: '#4f6fb3',
          500: '#34528f',
          600: '#243c6e',
          700: '#1a2c52',
          800: '#121f3a',
          900: '#0c1628', // primary background
          950: '#070d18', // deepest panel / sidebar
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
          gray: '#475569',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(0,0,0,0.25), 0 1px 3px rgba(0,0,0,0.30)',
        lift: '0 8px 24px rgba(0,0,0,0.40)',
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
