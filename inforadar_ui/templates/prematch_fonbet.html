<!-- inforadar_ui/templates/prematch_fonbet.html -->
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Fonbet • Prematch</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 18px; }
    .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom: 12px; }
    select, button, input { padding: 8px 10px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid #eee; padding: 10px; text-align: left; }
    tr:hover { background: #fafafa; }
    .muted { color:#777; }
    .err { color:#b00020; white-space: pre-wrap; }
    .pill { display:inline-block; padding:2px 8px; border:1px solid #ddd; border-radius: 999px; font-size:12px; }
    a { color:#0b57d0; text-decoration:none; }
    a:hover { text-decoration:underline; }
  </style>
</head>
<body>
  <h2>Fonbet • Prematch</h2>

  <div class="row">
    <label>
      Окно (часов):
      <select id="hours">
        <option value="6">6</option>
        <option value="12" selected>12</option>
        <option value="24">24</option>
        <option value="48">48</option>
      </select>
    </label>

    <label>
      Sport:
      <select id="sport"></select>
    </label>

    <button id="reload">Обновить</button>
    <span class="muted" id="status"></span>
  </div>

  <div class="err" id="error"></div>

  <table>
    <thead>
      <tr>
        <th>Время</th>
        <th>Лига</th>
        <th>Матч</th>
        <th>SportID</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="tbody">
      <tr><td colspan="5" class="muted">Loading…</td></tr>
    </tbody>
  </table>

<script>
  const hoursEl = document.getElementById('hours');
  const sportEl = document.getElementById('sport');
  const tbody = document.getElementById('tbody');
  const statusEl = document.getElementById('status');
  const errorEl = document.getElementById('error');
  const reloadBtn = document.getElementById('reload');

  function setError(msg) {
    errorEl.textContent = msg || '';
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, m => ({
      '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
    }[m]));
  }

  async function loadSportsAndDefault() {
    const hours = Number(hoursEl.value || 12);
    const r = await fetch(`/api/fonbet/sports?hours=${encodeURIComponent(hours)}`);
    if (!r.ok) throw new Error(`sports HTTP ${r.status}`);
    const data = await r.json();

    const sports = data.sports || [];
    const defaultSportId = Number(data.default_sport_id || 0);

    sportEl.innerHTML = '';
    // add "All"
    const optAll = document.createElement('option');
    optAll.value = '0';
    optAll.textContent = 'All (0)';
    sportEl.appendChild(optAll);

    for (const s of sports) {
      const opt = document.createElement('option');
      opt.value = String(s.sport_id);
      opt.textContent = `${s.name} (${s.count}) [${s.sport_id}]`;
      sportEl.appendChild(opt);
    }

    // prefer football/default id
    sportEl.value = String(defaultSportId || 0);
  }

  async function loadEvents() {
    setError('');
    const hours = Number(hoursEl.value || 12);
    const sportId = Number(sportEl.value || 0);
    statusEl.textContent = 'Loading…';

    const url = `/api/fonbet/events?hours=${encodeURIComponent(hours)}&sport_id=${encodeURIComponent(sportId)}&limit=500`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(`events HTTP ${r.status}`);

    const data = await r.json();
    const events = data.events || [];

    tbody.innerHTML = '';
    if (!events.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="muted">Пусто</td></tr>`;
      statusEl.textContent = '0 событий';
      return;
    }

    for (const e of events) {
      const tr = document.createElement('tr');
      const matchup = `${escapeHtml(e.team1)} — ${escapeHtml(e.team2)}`.trim();
      tr.innerHTML = `
        <td>${escapeHtml(e.start_time)}</td>
        <td>${escapeHtml(e.league_name || '-')}</td>
        <td>${matchup || '<span class="muted">-</span>'}</td>
        <td><span class="pill">${escapeHtml(e.sport_id)}</span></td>
        <td><a href="/fonbet_event/${encodeURIComponent(e.event_id)}">Открыть</a></td>
      `;
      tbody.appendChild(tr);
    }

    statusEl.textContent = `${events.length} событий`;
  }

  async function refreshAll() {
    try {
      await loadSportsAndDefault();
      await loadEvents();
    } catch (e) {
      setError(String(e));
      statusEl.textContent = 'Ошибка';
    }
  }

  reloadBtn.addEventListener('click', () => loadEvents().catch(e => {
    setError(String(e));
    statusEl.textContent = 'Ошибка';
  }));

  hoursEl.addEventListener('change', () => refreshAll());
  sportEl.addEventListener('change', () => loadEvents().catch(e => setError(String(e))));

  // initial
  refreshAll();
</script>
</body>
</html>
