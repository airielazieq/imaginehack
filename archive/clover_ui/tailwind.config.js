/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Clover brand green scale
        clover: {
          50: '#f0f9f1',
          100: '#dbf0de',
          200: '#bae3c1',
          300: '#8bcd97',
          400: '#56b069',
          500: '#2f9e44', // primary
          600: '#258139',
          700: '#216632',
          800: '#1d502b',
          900: '#163d22',
          950: '#0a2614', // deep sidebar
        },
        // Warm neutral canvas
        sand: {
          50: '#fafaf7',
          100: '#f3f3ee',
          200: '#e7e7df',
          300: '#d4d4c8',
        },
        sev: {
          critical: '#dc2626',
          high: '#ea580c',
          medium: '#ca8a04',
          low: '#16a34a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.06)',
        lift: '0 8px 24px rgba(16,40,24,0.10)',
      },
      borderRadius: {
        xl: '0.875rem',
      },
    },
  },
  plugins: [],
}
