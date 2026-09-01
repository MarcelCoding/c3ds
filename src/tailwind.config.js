/** @type {import('tailwindcss').Config} */

import defaultTheme from 'tailwindcss/defaultTheme';

export default {
  content: [
      "./c3ds/static/**/*.{vue,js,ts,jsx,tsx}",
      "./c3ds/*/templates/**/*.html",
      "./c3ds/*/static/**/*.{vue,js,ts,jsx,tsx,html}",
  ],
  safelist: [
    {
      pattern: /m-(1|2|3|4|5|6|7|8)/, // You can display all the colors that you need
      variants: ['lg', 'hover', 'focus', 'lg:hover'],      // Optional
    },
    {
      pattern: /text-(1|2|3|4|5|6|7|8|9)xl/, // You can display all the colors that you need
      variants: ['lg', 'hover', 'focus', 'lg:hover'],      // Optional
    },
    {
      pattern: /items-.*/,
    },
  ],
  theme: {
    extend: {
      // Datenspuren 2026 palette, see https://datenspuren.de/2026/style/2026.css
      // The actual values live in css/base.scss so that the light variant
      // (magenta background) and the dark variant (black background) can be
      // switched with a single body class.
      colors: {
        // semantic tokens
        fg: 'var(--color-fg)',
        bg: 'var(--color-bg)',
        accent: 'var(--color-accent)',
        muted: 'var(--color-muted)',
        line: 'var(--color-line)',
        'line-soft': 'var(--color-line-soft)',
        progress: 'var(--color-progress)',

        // legacy token names, kept so existing markup keeps working
        dark: 'var(--color-dark)',
        neutral: 'var(--color-fg)',
        primary: 'var(--color-fg)',
        secondary: 'var(--color-accent)',
        highlight: 'var(--color-fg)',
        background: 'var(--color-bg)',
      },
      fontFamily: {
        'headline': ['GeneraleStation', ...defaultTheme.fontFamily.sans],
        'display': ['Horta', 'GeneraleStation', ...defaultTheme.fontFamily.sans],
        'sans': ['Cabin', ...defaultTheme.fontFamily.sans],
        'sans-condensed': ['Cabin', ...defaultTheme.fontFamily.sans],
        'numbers': ['Cabin', ...defaultTheme.fontFamily.sans],
      },
      gridTemplateColumns: {
        'schedule': 'max-content 15px 1fr',
      }
    },
  },
  plugins: [],
}
