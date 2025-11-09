async function loadMatches() {
  try {
    const response = await fetch('/api/matches');
    const data = await response.json();
    const tbody = document.querySelector('#matches-table tbody');
    tbody.innerHTML = '';

    data.forEach(match => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${match.sport}</td>
        <td>${match.league}</td>
        <td>${match.home_team}</td>
        <td>${match.away_team}</td>
        <td>${match.score_home} - ${match.score_away}</td>
        <td>${new Date(match.start_time).toLocaleString()}</td>
      `;
      tbody.appendChild(row);
    });
  } catch (err) {
    console.error('Ошибка загрузки данных:', err);
  }
}

setInterval(loadMatches, 5000);
window.onload = loadMatches;
