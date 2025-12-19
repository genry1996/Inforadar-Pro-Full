// Конфигурация
const CONFIG = {
    autoRefreshInterval: 10000, // 10 секунд
    apiBaseUrl: '/api/betwatch'
};

// Состояние
let currentFilter = 'all';
let currentTimeRange = 24;
let autoRefreshEnabled = true;
let refreshTimer = null;

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    initFilters();
    initTimeRange();
    initRefreshButton();
    loadSignals();
    loadStats();
    startAutoRefresh();
});

// Фильтры по типу
function initFilters() {
    const filterButtons = document.querySelectorAll('.filter-btn');
    
    filterButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            // Убираем active со всех
            filterButtons.forEach(b => b.classList.remove('active'));
            
            // Добавляем active на текущую
            this.classList.add('active');
            
            // Обновляем фильтр
            currentFilter = this.getAttribute('data-type');
            loadSignals();
        });
    });
}

// Фильтр по времени
function initTimeRange() {
    const timeRange = document.getElementById('time-range');
    
    timeRange.addEventListener('change', function() {
        currentTimeRange = this.value;
        loadSignals();
        loadStats();
    });
}

// Кнопка обновления
function initRefreshButton() {
    const refreshBtn = document.getElementById('refresh-btn');
    
    refreshBtn.addEventListener('click', function() {
        loadSignals();
        loadStats();
    });
}

// Загрузка сигналов
async function loadSignals() {
    const tbody = document.getElementById('signals-body');
    tbody.innerHTML = '<tr><td colspan="9" class="loading">Loading...</td></tr>';
    
    try {
        const response = await fetch(
            `${CONFIG.apiBaseUrl}/signals?type=${currentFilter}&hours=${currentTimeRange}&limit=50`
        );
        
        if (!response.ok) throw new Error('Failed to load signals');
        
        const data = await response.json();
        
        if (data.signals.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="loading">No signals found</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.signals.map(signal => `
            <tr>
                <td><span class="signal-type ${signal.signal_type}">${formatSignalType(signal.signal_type)}</span></td>
                <td><strong>${signal.event_name}</strong></td>
                <td>${signal.league || 'N/A'}</td>
                <td>${signal.market_type || 'N/A'}</td>
                <td>${signal.betfair_odd ? signal.betfair_odd.toFixed(2) : 'N/A'}</td>
                <td>${signal.odd_drop_percent ? `<strong>${signal.odd_drop_percent.toFixed(1)}%</strong>` : '-'}</td>
                <td>${signal.money_volume ? `€${signal.money_volume.toLocaleString()}` : '-'}</td>
                <td>${signal.flow_percent ? `<strong>${signal.flow_percent.toFixed(1)}%</strong>` : '-'}</td>
                <td>${formatTime(signal.detected_at)}</td>
            </tr>
        `).join('');
        
        updateLastUpdate();
        
    } catch (error) {
        console.error('Error loading signals:', error);
        tbody.innerHTML = '<tr><td colspan="9" class="loading">Error loading signals</td></tr>';
    }
}

// Загрузка статистики
async function loadStats() {
    try {
        const response = await fetch(`${CONFIG.apiBaseUrl}/stats?hours=${currentTimeRange}`);
        
        if (!response.ok) throw new Error('Failed to load stats');
        
        const data = await response.json();
        
        // Обновляем карточки
        document.getElementById('total-signals').textContent = data.total;
        
        // Подсчитываем по типам
        let sharpDrops = 0, valueBets = 0, unbalanced = 0;
        
        data.by_type.forEach(item => {
            if (item.signal_type === 'sharp_drop') sharpDrops = item.count;
            if (item.signal_type === 'value_bet') valueBets = item.count;
            if (item.signal_type === 'unbalanced_flow') unbalanced = item.count;
        });
        
        document.getElementById('sharp-drops').textContent = sharpDrops;
        document.getElementById('value-bets').textContent = valueBets;
        document.getElementById('unbalanced').textContent = unbalanced;
        
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Авто-обновление
function startAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    
    refreshTimer = setInterval(() => {
        if (autoRefreshEnabled) {
            loadSignals();
            loadStats();
        }
    }, CONFIG.autoRefreshInterval);
}

// Форматирование
function formatSignalType(type) {
    const types = {
        'sharp_drop': '📉 Drop',
        'value_bet': '💎 Value',
        'unbalanced_flow': '⚖️ Flow',
        'minor_league_spike': '🎯 Minor',
        'total_over_spike': '📈 Over',
        'late_game_spike': '⏰ Late'
    };
    return types[type] || type;
}

function formatTime(timestamp) {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp);
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function updateLastUpdate() {
    const now = new Date();
    document.getElementById('last-update').textContent = now.toLocaleTimeString('ru-RU');
}
