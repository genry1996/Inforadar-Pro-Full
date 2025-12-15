let currentData = [];
let filteredData = [];

// Load test data
async function loadData() {
    try {
        const response = await fetch('/api/anomalies/test');
        if (!response.ok) {
            throw new Error('Failed to fetch');
        }
        const data = await response.json();
        currentData = data || [];
        filteredData = data || [];
        renderTable(filteredData);
        updateStats(filteredData);
    } catch (error) {
        console.error('Error loading data:', error);
        currentData = [];
        filteredData = [];
    }
}

// Render table
function renderTable(data) {
    const tbody = document.getElementById('tableBody');
    tbody.innerHTML = '';
    
    data.forEach(anomaly => {
        const row = document.createElement('tr');
        const anomalyType = anomaly.anomaly_type || 'ODDS_DROP';
        const severity = anomaly.severity || 'medium';
        row.innerHTML = `
            <td><span class="anomaly-icon" title="${anomalyType}">🔴</span></td>
            <td>${anomaly.event_name || 'N/A'}</td>
            <td>${anomaly.created_at || 'Just now'}</td>
            <td>${anomaly.sport || ''} ${anomaly.league || ''}</td>
            <td>${anomaly.old_odd} → ${anomaly.new_odd} (${anomaly.change_percent || 0}%)</td>
            <td>${anomalyType}</td>
            <td><span class="severity-${severity}">${severity.toUpperCase()}</span></td>
            <td><button class="btn btn-primary" onclick="openModal(${JSON.stringify(anomaly).replace(/"/g, '&quot;')})">View</button></td>
        `;
        tbody.appendChild(row);
    });
}

// Update stats
function updateStats(data) {
    document.getElementById('statsTotal').textContent = data.length;
    const critical = data.filter(a => a.severity === 'critical').length;
    document.getElementById('statsCritical').textContent = critical;
}

// Corridor Width Slider - ИСПРАВЛЕНО!
function updateCorridorValue() {
    const corridorSlider = document.getElementById('corridorWidth');
    const corridorValueDisplay = document.getElementById('corridorWidthValue');
    if (corridorSlider && corridorValueDisplay) {
        corridorValueDisplay.textContent = corridorSlider.value + '%';
    }
}

// Initialize slider listeners
const corridorSlider = document.getElementById('corridorWidth');
if (corridorSlider) {
    corridorSlider.addEventListener('input', updateCorridorValue);
    corridorSlider.addEventListener('change', updateCorridorValue);
}

// Corridor checkbox
const anomCorridorCheckbox = document.getElementById('anom_corridor');
if (anomCorridorCheckbox) {
    anomCorridorCheckbox.addEventListener('change', function() {
        const corridorFilters = document.getElementById('corridorFilters');
        if (this.checked) {
            corridorFilters.style.display = 'block';
            corridorFilters.classList.add('visible');
        } else {
            corridorFilters.style.display = 'none';
            corridorFilters.classList.remove('visible');
        }
    });
}

// VALUEBETDIFF checkbox
const anomValuebetCheckbox = document.getElementById('anom_valuebetdiff');
if (anomValuebetCheckbox) {
    anomValuebetCheckbox.addEventListener('change', function() {
        const comparisonFilters = document.getElementById('comparisonFilters');
        if (this.checked) {
            comparisonFilters.style.display = 'block';
            comparisonFilters.classList.add('visible');
        } else {
            comparisonFilters.style.display = 'none';
            comparisonFilters.classList.remove('visible');
        }
    });
}

// Sport filter - show league grid
const filterSportSelect = document.getElementById('filterSport');
if (filterSportSelect) {
    filterSportSelect.addEventListener('change', function() {
        const leagueContainer = document.getElementById('leagueGridContainer');
        if (this.value) {
            leagueContainer.classList.add('visible');
            leagueContainer.style.display = 'grid';
            
            const leagues = ['Premier League', 'La Liga', 'Serie A', 'Bundesliga', 'Ligue 1'];
            leagueContainer.innerHTML = leagues.map(league => 
                `<div class="league-card" onclick="toggleLeague(this)">${league}</div>`
            ).join('');
        } else {
            leagueContainer.classList.remove('visible');
            leagueContainer.style.display = 'none';
        }
    });
}

// Toggle league selection
function toggleLeague(element) {
    element.classList.toggle('selected');
}

// Accordion toggle
document.querySelectorAll('.filter-accordion-header').forEach(header => {
    header.addEventListener('click', function() {
        const body = this.nextElementSibling;
        body.classList.toggle('active');
    });
});

// Apply filters
const btnApplyFilters = document.getElementById('btnApplyFilters');
if (btnApplyFilters) {
    btnApplyFilters.addEventListener('click', function() {
        const changePct = parseFloat(document.getElementById('filterChangePct').value);
        filteredData = currentData.filter(a => Math.abs(a.change_percent || 0) >= changePct);
        renderTable(filteredData);
        updateStats(filteredData);
        
        const msg = document.getElementById('successMessage');
        document.getElementById('resultCount').textContent = filteredData.length;
        msg.classList.add('visible');
        msg.style.display = 'block';
        setTimeout(() => {
            msg.classList.remove('visible');
            msg.style.display = 'none';
        }, 3000);
    });
}

// Reset filters
const btnResetFilters = document.getElementById('btnResetFilters');
if (btnResetFilters) {
    btnResetFilters.addEventListener('click', function() {
        document.getElementById('filterChangePct').value = '5';
        document.getElementById('filterSeverity').value = '';
        document.getElementById('filterSport').value = '';
        filteredData = currentData;
        renderTable(currentData);
        updateStats(currentData);
    });
}

// Modal functions
function openModal(anomaly) {
    document.getElementById('modal_event_name').textContent = anomaly.event_name || 'N/A';
    document.getElementById('modal_sport').textContent = anomaly.sport || 'N/A';
    document.getElementById('modal_league').textContent = anomaly.league || 'N/A';
    document.getElementById('modal_market').textContent = anomaly.market_type || 'N/A';
    document.getElementById('modal_old_odd').textContent = anomaly.old_odd || 'N/A';
    document.getElementById('modal_new_odd').textContent = anomaly.new_odd || 'N/A';
    document.getElementById('modal_change').textContent = (anomaly.change_percent || 0) + '%';
    document.getElementById('modal_type').textContent = anomaly.anomaly_type || 'N/A';
    document.getElementById('modal_severity').textContent = anomaly.severity || 'N/A';
    document.getElementById('modal_comment').textContent = anomaly.comment || 'No comment';
    
    document.getElementById('detailModal').classList.add('active');
}

const btnCloseModal = document.getElementById('btnCloseModal');
if (btnCloseModal) {
    btnCloseModal.addEventListener('click', function() {
        document.getElementById('detailModal').classList.remove('active');
    });
}

// Close modal on backdrop click
const detailModal = document.getElementById('detailModal');
if (detailModal) {
    detailModal.addEventListener('click', function(e) {
        if (e.target === this) {
            this.classList.remove('active');
        }
    });
}

// Load data on page load
window.addEventListener('DOMContentLoaded', () => {
    loadData();
    // Initialize slider value after DOM is ready
    setTimeout(updateCorridorValue, 100);
});
