/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        background: '#fafaf8',
        foreground: '#111110',
        card: '#ffffff',
        'card-foreground': '#111110',
        primary: '#111110',
        'primary-foreground': '#fafaf8',
        secondary: '#f0ede8',
        'secondary-foreground': '#111110',
        muted: '#e8e5e0',
        'muted-foreground': '#6b6860',
        accent: '#c0392b',
        'accent-foreground': '#ffffff',
        border: '#d4d0cb',
      },
      fontFamily: {
        display: ['"Playfair Display"', 'Georgia', 'serif'],
        'mono-editorial': ['"Space Mono"', 'monospace'],
      },
    },
  },
  plugins: [],
};
