from flask import Flask

app = Flask(__name__)

@app.route('/anomalies_22bet')
def anomalies_22bet():
    return '''
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>22BET Anomalies</title></head>
<body>
    <h1>Betting Anomalies Monitor</h1>
    
    <div class="stats-container">
        <span id="statsTotal">3</span>
    </div>
    
    <div class="status-badge">Live</div>
    
    <!-- Filters -->
    <div class="filters-panel">
        <input type="checkbox" id="anom_odds_drop" checked>
        <input type="checkbox" id="anom_corridor">
        <input type="checkbox" id="anom_valuebetdiff">
        
        <div id="corridorFilters" style="display:none;">
            <input type="range" id="corridorWidth" min="0" max="10" value="5">
        </div>
        
        <div id="comparisonFilters" style="display:none;">
            <select id="comparisonOperator">
                <option value="gt">Greater Than</option>
            </select>
        </div>
        
        <select id="filterSport">
            <option value="">All Sports</option>
            <option value="football">Football</option>
            <option value="tennis">Tennis</option>
        </select>
        
        <input type="number" id="filterChangePct" placeholder="Change %">
        <select id="filterSeverity">
            <option value="">All</option>
            <option value="critical">Critical</option>
        </select>
        
        <button id="btnApplyFilters">Apply Filters</button>
        <button id="btnResetFilters">Reset</button>
    </div>
    
    <div id="leagueGridContainer" style="display:none;">
        <div class="league-card">Premier League</div>
        <div class="league-card">La Liga</div>
    </div>
    
    <div class="filter-accordion">
        <div class="filter-accordion-header">Type Filters</div>
        <div class="filter-accordion-body">Body 1</div>
    </div>
    
    <table class="anomalies-table">
        <thead>
            <tr><th>Event</th><th>Type</th><th>Change</th><th>Time</th><th>Actions</th></tr>
        </thead>
        <tbody>
            <tr>
                <td>Manchester United vs Liverpool</td>
                <td><span class="anomaly-icon" title="ODDS_DROP">ODDS_DROP</span></td>
                <td>-28.0%</td>
                <td>2025-12-14 16:00:00</td>
                <td><button class="view-btn">View</button></td>
            </tr>
            <tr>
                <td>Real Madrid vs Barcelona</td>
                <td><span class="anomaly-icon" title="CORRIDOR">CORRIDOR</span></td>
                <td>+2.38%</td>
                <td>2025-12-14 15:30:00</td>
                <td><button class="view-btn">View</button></td>
            </tr>
            <tr>
                <td>Bayern Munich vs Dortmund</td>
                <td><span class="anomaly-icon severity-critical" title="LIMIT_CUT">LIMIT_CUT</span></td>
                <td>-45.0%</td>
                <td>2025-12-14 14:00:00</td>
                <td><button class="view-btn">View</button></td>
            </tr>
        </tbody>
    </table>
    
    <div id="detailModal" class="modal">
        <div class="modal-content">
            <button id="btnCloseModal">×</button>
            <h2>Anomaly Details</h2>
            <div class="modal-field-label">Event Name:</div>
            <div class="modal-field-label">Sport:</div>
            <div class="modal-field-label">League:</div>
            <div class="modal-field-label">Anomaly Type:</div>
            <div class="modal-field-label">Old Odd:</div>
            <div class="modal-field-label">New Odd:</div>
            <div class="modal-field-label">Change %:</div>
            <div class="modal-field-label">Detected At:</div>
            <div class="modal-field-label">Status:</div>
            <div class="modal-field-label">Comment:</div>
        </div>
    </div>
    
    <script>
        // View buttons
        document.querySelectorAll('.view-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.getElementById('detailModal').classList.add('active');
            });
        });
        
        // Close modal
        document.getElementById('btnCloseModal').addEventListener('click', () => {
            document.getElementById('detailModal').classList.remove('active');
        });
        
        document.getElementById('detailModal').addEventListener('click', (e) => {
            if (e.target.id === 'detailModal') {
                e.target.classList.remove('active');
            }
        });
        
        // Sport filter
        document.getElementById('filterSport').addEventListener('change', (e) => {
            document.getElementById('leagueGridContainer').style.display = 
                e.target.value ? 'block' : 'none';
        });
        
        // League cards
        document.querySelectorAll('.league-card').forEach(card => {
            card.addEventListener('click', () => {
                card.classList.toggle('selected');
            });
        });
        
        // Accordion
        document.querySelectorAll('.filter-accordion-header').forEach(header => {
            header.addEventListener('click', () => {
                header.nextElementSibling.classList.toggle('active');
            });
        });
        
        // Corridor checkbox
        document.getElementById('anom_corridor').addEventListener('change', (e) => {
            document.getElementById('corridorFilters').style.display = 
                e.target.checked ? 'block' : 'none';
        });
        
        // ValueBetDiff checkbox
        document.getElementById('anom_valuebetdiff').addEventListener('change', (e) => {
            document.getElementById('comparisonFilters').style.display = 
                e.target.checked ? 'block' : 'none';
        });
        
        // Apply filters
        document.getElementById('btnApplyFilters').addEventListener('click', () => {
            alert('Filters applied successfully!');
        });
        
        // Reset filters
        document.getElementById('btnResetFilters').addEventListener('click', () => {
            document.getElementById('filterChangePct').value = '';
            document.getElementById('filterSeverity').value = '';
        });
    </script>
</body>
</html>
    '''

@app.route('/metrics')
def metrics():
    return 'ok\n', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
