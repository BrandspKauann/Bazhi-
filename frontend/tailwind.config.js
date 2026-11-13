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
        primary: '#e42859',
        teal: {50:'#fff1f5',100:'#ffe0e8',200:'#ffc2d2',300:'#ff94b1',400:'#f65b87',500:'#e42859',600:'#cb1648',700:'#a9123c',800:'#8d1337',900:'#771632'},
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