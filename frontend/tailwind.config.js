module.exports = {
  darkMode: 'class',
  content: [
    './index.html',
    './src/**/*.{js,jsx,ts,tsx}'
  ],
  theme: {
    extend: {
      colors: {
        // primary color used throughout the app; can be changed globally
        primary: '#00B36B',
        teal: {50:'#EDFFF5',100:'#D1FAE3',200:'#A1F3C8',300:'#65E9A6',400:'#28D887',500:'#00B36B',600:'#00834D',700:'#00683E',800:'#075333',900:'#08442C'},
        emerald: {50:'#EDFFF5',100:'#D1FAE3',200:'#A1F3C8',300:'#65E9A6',400:'#28D887',500:'#00B36B',600:'#00834D',700:'#00683E',800:'#075333',900:'#08442C'},
        bazhi: {green:'#00B36B',yellow:'#FFD200',red:'#E60012',ink:'#0B0F1A',white:'#F5F7FA'},
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont',
          '"Segoe UI"', 'Roboto', '"Helvetica Neue"', 'Arial', '"Noto Sans"', 'sans-serif'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'), // better base styling for form controls
  ]
};