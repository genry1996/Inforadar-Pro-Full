Quick Start (Inforadar_Pro)

1) Create .env (Telegram for Alertmanager) next to docker-compose.yml:
   ALERTMANAGER_TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
   ALERTMANAGER_TELEGRAM_CHAT_ID=YOUR_CHAT_ID

2) Start:
   docker compose up -d --build

3) Open:
   - Grafana:      http://localhost:3000  (admin / admin)
   - Prometheus:   http://localhost:9090
   - Alertmanager: http://localhost:9093
   - UI (Flask):   http://localhost:5000
   - Loki API:     http://localhost:3100
   - cAdvisor:     http://localhost:8085

Troubleshooting (Windows):
- If you see 'not a directory' on mounts, ensure files exist and paths are correct.
- For 'orphan containers' use --remove-orphans.
- If Docker Desktop hangs, restart Docker Desktop/WSL2.
