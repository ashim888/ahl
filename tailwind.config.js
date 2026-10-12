/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html', './static/js/**/*.js'],
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
        // The red for text on dark (bg-foreground) sections — #c0392b is only
        // 3.5:1 there; this is ~6:1 (WCAG AA). Applied automatically, see input.css.
        'accent-on-dark': '#ef6b5c',
        'accent-foreground': '#ffffff',
        border: '#d4d0cb',
      },
      fontFamily: {
        // Noto Sans/Serif Devanagari before the Latin fallback — Playfair
        // Display/Space Mono have no Devanagari glyphs at all. Kept in
        // sync with the matching (and, in the browser, actually-winning —
        // see the <style> block's own comment) declarations in
        // templates/base.html.
        display: ['"Playfair Display"', '"Noto Serif Devanagari"', 'Georgia', 'serif'],
        'mono-editorial': ['"Space Mono"', '"Noto Sans Devanagari"', 'monospace'],
      },
    },
  },
  plugins: [],
};
