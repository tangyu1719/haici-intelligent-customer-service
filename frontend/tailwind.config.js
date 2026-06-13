/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,ts,js}'],
  theme: {
    extend: {
      colors: {
        haici: {
          dark: '#363e42',
          accent: '#d97706',
          accent2: '#b45309',
        },
      },
      fontSize: {
        '2xs': ['10px', '1.4'],
        xs: ['11px', '1.5'],
        sm: ['12px', '1.5'],
        base: ['13px', '1.6'],
      },
    },
  },
  plugins: [],
}
