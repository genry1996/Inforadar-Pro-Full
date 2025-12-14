export default defineConfig({
  // ...
  use: {
    baseURL: 'http://localhost:5000',  // Зависит от того, на каком порту Flask
  },
  
  webServer: {
    command: 'python inforadar_ui/app.py',  // Или как у тебя запускается Flask
    url: 'http://localhost:5000',
    reuseExistingServer: !process.env.CI,
  },
});
