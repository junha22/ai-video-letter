import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        ongi: {
          50: '#FDFBF7',
          100: '#F7F2E9',
          200: '#EFE5D3',
          300: '#E2CEB0',
          400: '#D5B48B',
          500: '#C69363',
          600: '#B07845',
          700: '#8E5A2D',
          800: '#6C421F',
          900: '#4E2F16',
        },
        warmOrange: {
          50: '#FFF8F3',
          100: '#FEEFE6',
          200: '#FCD8C5',
          300: '#F9B79B',
          400: '#F28E69',
          500: '#E66B40',
          600: '#CB4E22',
        },
        sageGreen: {
          50: '#F3F7F4',
          100: '#E4EDE7',
          200: '#C8DCCF',
          300: '#A3C4AF',
          400: '#7AA78A',
          500: '#588A6A',
          600: '#416D51',
        },
        senior: {
          bg: '#FFFDF9',
          card: '#FFFFFF',
          border: '#E8DFD3',
          text: '#1F1A16',
          subtext: '#594F45',
          accent: '#C75D2C',
        }
      },
      fontFamily: {
        sans: ['Pretendard', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      keyframes: {
        wave: {
          '0%, 100%': { height: '8px' },
          '50%': { height: '32px' },
        },
        pulseSlow: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.85', transform: 'scale(1.03)' },
        }
      },
      animation: {
        'wave-1': 'wave 1s ease-in-out infinite',
        'wave-2': 'wave 1.2s ease-in-out 0.2s infinite',
        'wave-3': 'wave 0.8s ease-in-out 0.4s infinite',
        'wave-4': 'wave 1.1s ease-in-out 0.1s infinite',
        'pulse-slow': 'pulseSlow 3s ease-in-out infinite',
      }
    },
  },
  plugins: [],
};
export default config;
