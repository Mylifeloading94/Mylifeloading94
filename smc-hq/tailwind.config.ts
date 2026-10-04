import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0b0b14',
        paper: '#fff6d6',
        pop: { yellow: '#ffd426', red: '#ff3b3b', blue: '#2fa8ff', green: '#2bff88', pink: '#ff4fd8', purple: '#7a4dff' },
      },
      fontFamily: {
        comic: ['Bangers', 'Impact', 'Haettenschweiler', 'Arial Narrow Bold', 'sans-serif'],
        pixel: ['"Press Start 2P"', 'ui-monospace', 'monospace'],
        body: ['"Comic Neue"', '"Comic Sans MS"', 'ui-rounded', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        comic: '4px 4px 0 0 #0b0b14',
        comicLg: '7px 7px 0 0 #0b0b14',
      },
    },
  },
  plugins: [],
};
export default config;
