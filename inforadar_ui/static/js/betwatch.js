// Конфигурация
const CONFIG = {
    autoRefreshInterval: 10000, // 10 секунд
    apiBaseUrl: '/api/betwatch'
};

// Маппинг лиг к кодам стран (ISO 3166-1 alpha-2)
const LEAGUE_COUNTRY_MAP = {
    'Premier League': 'gb-eng',
    'La Liga': 'es',
    'Serie A': 'it',
    'Bundesliga': 'de',
    'Ligue 1': 'fr',
    'Eredivisie': 'nl',
    'Primeira Liga': 'pt',
    'Championship': 'gb-eng',
    'Champions League': 'eu',
    'Europa League': 'eu',
    'World Cup': 'fifa',
    'Euro': 'eu',
    
    // Восточная Европа
    'Russian Premier League': 'ru',
    'Ukrainian Premier League': 'ua',
    'Croatian HNL': 'hr',
    'Serbian SuperLiga': 'rs',
    'Polish Ekstraklasa': 'pl',
    'Czech First League': 'cz',
    'Hungarian NB I': 'hu',
    'Romanian Liga 1': 'ro',
    'Bulgarian First League': 'bg',
    
    // Африка
    'Egyptian League': 'eg',
    'Egyptian Premier League': 'eg',
    'Egyptian League Cup': 'eg',
    'South African Premier': 'za',
    'Moroccan Botola': 'ma',
    'Ethiopian Premier League': 'et',
    'Algerian Ligue 1': 'dz',
    
    // Азия
    'Qatari Stars League': 'qa',
    'Qatar U23 League': 'qa',
    'Qatari U23 League': 'qa',
    'U23 League': 'qa',
    'Kuwaiti Premier League': 'kw',
    'Saudi Pro League': 'sa',
    'UAE Pro League': 'ae',
    'Omani Professional League': 'om',
    'Oman Professional League': 'om',
    'Bahraini Premier': 'bh',
    'Bahraini Premier League': 'bh',
    'Iraqi Premier League': 'iq',
    'Jordanian Pro League': 'jo',
    'Chinese Super League': 'cn',
    'J-League': 'jp',
    'K League': 'kr',
    'Singapore Premier League': 'sg',
    'Singapore Premier League 2': 'sg',
    'Thai League': 'th',
    'Vietnamese V.League': 'vn',
    'Indonesian Liga 1': 'id',
    'Malaysian Super League': 'my',
    'National Football League': 'lr',
    
    // Балканы
    'Albanian Superliga': 'al',
    'Greek Super League': 'gr',
    'Turkish Super Lig': 'tr',
    'Bosnian Premier League': 'ba',
};

// Состояние
let currentFilter = 'all';
let currentLiveFilter = 'all'; // all / live / prematch
let currentTimeRange = 24;
let autoRefreshEnabled = true;
let refreshTimer = null;

// Инициализация
document.addEventListener('DOMContentLoaded', function() {
    initFilters();
    initLivePrematchFilters();
    initTimeRange();
    initRefreshButton();
    loadSignals();
    loadStats();
    startAutoRefresh();
});

// Фильтры по типу сигнала
function initFilters() {
    const filterButtons = document.querySelectorAll('.filter-btn');
    
    filterButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            filterButtons.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentFilter = this.getAttribute('data-type');
            loadSignals();
        });
    });
}

// Фильтры Live / Prematch
function initLivePrematchFilters() {
    const liveFilterButtons = document.querySelectorAll('[data-live-filter]');
    
    liveFilterButtons.forEach(btn => {
        btn.addEventListener('click', function() {
            liveFilterButtons.forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            currentLiveFilter = this.getAttribute('data-live-filter');
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

// Определение кода страны по лиге
function getCountryCode(league) {
    if (!league) return null;
    
    // Прямое совпадение
    if (LEAGUE_COUNTRY_MAP[league]) {
        return LEAGUE_COUNTRY_MAP[league];
    }
    
    // Частичное совпадение
    const leagueLower = league.toLowerCase();
    for (let [key, code] of Object.entries(LEAGUE_COUNTRY_MAP)) {
        if (leagueLower.includes(key.toLowerCase())) {
            return code;
        }
    }
    
    // Поиск по ключевым словам
    const keywords = {
        'egypt': 'eg', 'qatar': 'qa', 'bahrain': 'bh', 'kuwait': 'kw',
        'saudi': 'sa', 'emirati': 'ae', 'uae': 'ae', 'oman': 'om',
        'iraq': 'iq', 'jordan': 'jo', 'syria': 'sy', 'lebanon': 'lb',
        'albania': 'al', 'croatia': 'hr', 'ethiopia': 'et',
        'singapore': 'sg', 'algeria': 'dz', 'morocco': 'ma',
        'tunisia': 'tn', 'nigeria': 'ng', 'kenya': 'ke',
        'china': 'cn', 'japan': 'jp', 'korea': 'kr', 'india': 'in',
        'thailand': 'th', 'vietnam': 'vn', 'malaysia': 'my',
        'indonesia': 'id', 'bulgaria': 'bg', 'romania': 'ro',
        'liberia': 'lr', 'liberian': 'lr'
    };
    
    for (let [keyword, code] of Object.entries(keywords)) {
        if (leagueLower.includes(keyword)) {
            return code;
        }
    }
    
    return null;
}

// Форматирование типа сигнала
function formatSignalType(type) {
    const types = {
        'sharp_drop': { icon: '📉', text: 'Drop', class: 'signal-sharp-drop' },
        'value_bet': { icon: '💎', text: 'Value', class: 'signal-value-bet' },
        'unbalanced_flow': { icon: '⚖️', text: 'Flow', class: 'signal-unbalanced' },
        'total_over_spike': { icon: '📈', text: 'Total', class: 'signal-total-over' },
        'late_game_spike': { icon: '⏰', text: '80+', class: 'signal-late-game' }
    };
    
    const info = types[type] || { icon: '❓', text: type, class: 'signal-badge' };
    return `<span class="signal-badge ${info.class}">${info.icon} ${info.text}</span>`;
}

// Форматирование времени начала матча
function formatMatchTime(detectedAt) {
    if (!detectedAt) return '-';
    
    const date = new Date(detectedAt);
    const day = String(date.getDate()).padStart(2, '0');
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    
    return `${day}.${month}<br>${hours}:${minutes}`;
}

// Форматирование времени обнаружения
function formatDetectedTime(timestamp) {
    if (!timestamp) return 'N/A';
    const date = new Date(timestamp);
    return date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// Загрузка сигналов
async function loadSignals() {
    const tbody = document.getElementById('signals-body');
    tbody.innerHTML = '<tr><td colspan="12" class="loading">Загрузка...</td></tr>';
    
    try {
        const response = await fetch(
            `${CONFIG.apiBaseUrl}/signals?type=${currentFilter}&hours=${currentTimeRange}&limit=100`
        );
        
        if (!response.ok) throw new Error('Failed to load signals');
        
        const data = await response.json();
        
        if (data.signals.length === 0) {
            tbody.innerHTML = '<tr><td colspan="12" class="loading">Сигналы не найдены</td></tr>';
            return;
        }
        
        // Фильтрация по Live / Prematch
        let filteredSignals = data.signals;
        if (currentLiveFilter === 'live') {
            filteredSignals = data.signals.filter(s => s.is_live === 1 || s.is_live === true);
        } else if (currentLiveFilter === 'prematch') {
            filteredSignals = data.signals.filter(s => s.is_live === 0 || s.is_live === false || s.is_live === null);
        }
        
        if (filteredSignals.length === 0) {
            tbody.innerHTML = '<tr><td colspan="12" class="loading">Сигналы не найдены для выбранного фильтра</td></tr>';
            return;
        }
        
        tbody.innerHTML = filteredSignals.map(signal => {
            const countryCode = getCountryCode(signal.league || '');
            const flagHtml = countryCode 
                ? `<span class="fi fi-${countryCode}"></span>` 
                : '🌍';
            
            const moneyClass = signal.money_volume > 10000 ? 'money-high' : '';
            const flowClass = signal.flow_percent > 80 ? 'flow-high' : '';
            const dropClass = signal.odd_drop_percent && Math.abs(signal.odd_drop_percent) > 20 ? 'drop-high' : '';
            
            // Определяем статус Live/Prematch
            const isLive = signal.is_live === 1 || signal.is_live === true;
            const scoreCell = isLive 
                ? (signal.match_time ? `<span class="match-live">${signal.match_time}'</span>` : '<span class="match-live">🔴 Live</span>')
                : '<span class="match-prematch">📅 Prematch</span>';
            
            return `
                <tr onclick="showMatchDetails(${signal.id})">
                    <td>${formatMatchTime(signal.detected_at)}</td>
                    <td>${flagHtml}</td>
                    <td>${signal.league || '-'}</td>
                    <td><strong>${signal.event_name}</strong></td>
                    <td>${scoreCell}</td>
                    <td>${signal.market_type || '-'}</td>
                    <td>${formatSignalType(signal.signal_type)}</td>
                    <td>${signal.betfair_odd ? signal.betfair_odd.toFixed(2) : '-'}</td>
                    <td>${signal.bookmaker_odd ? signal.bookmaker_odd.toFixed(2) : '-'}</td>
                    <td class="${moneyClass}">${signal.money_volume ? '€' + signal.money_volume.toLocaleString() : '-'}</td>
                    <td class="${flowClass}">${signal.flow_percent ? signal.flow_percent.toFixed(1) + '%' : '-'}</td>
                    <td class="${dropClass}">${signal.odd_drop_percent ? signal.odd_drop_percent.toFixed(1) + '%' : '-'}</td>
                </tr>
            `;
        }).join('');
        
        updateLastUpdate();
        
    } catch (error) {
        console.error('Error loading signals:', error);
        tbody.innerHTML = '<tr><td colspan="12" class="loading">Ошибка загрузки данных</td></tr>';
    }
}

// Загрузка статистики
async function loadStats() {
    try {
        const response = await fetch(`${CONFIG.apiBaseUrl}/stats?hours=${currentTimeRange}`);
        
        if (!response.ok) throw new Error('Failed to load stats');
        
        const data = await response.json();
        
        document.getElementById('total-signals').textContent = data.total;
        
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

// Показать детали матча
async function showMatchDetails(signalId) {
    const modal = document.getElementById('match-modal');
    const modalBody = document.getElementById('modal-body');
    
    modalBody.innerHTML = `
        <h2>Детали сигнала #${signalId}</h2>
        <div class="loading-spinner">
            <p>⏳ Загрузка данных...</p>
        </div>
    `;
    
    modal.style.display = 'block';
    
    try {
        const response = await fetch(`${CONFIG.apiBaseUrl}/signal/${signalId}`);
        
        if (!response.ok) throw new Error('Failed to load signal details');
        
        const data = await response.json();
        const signal = data.signal;
        
        const countryCode = getCountryCode(signal.league || '');
        const flagHtml = countryCode 
            ? `<span class="fi fi-${countryCode}" style="font-size: 2em;"></span>` 
            : '🌍';
        
        const isLive = signal.is_live === 1 || signal.is_live === true;
        
        let html = `
            <div class="modal-header">
                <div class="modal-flag">${flagHtml}</div>
                <div class="modal-title">
                    <h2>${signal.event_name}</h2>
                    <p class="modal-league">${signal.league || 'Unknown League'}</p>
                    ${isLive ? '<span class="badge-live">🔴 LIVE ' + (signal.match_time || '') + "'</span>" : '<span class="badge-live" style="background: #007bff;">📅 PREMATCH</span>'}
                </div>
            </div>
            
            <div class="modal-grid">
                <div class="modal-card">
                    <h3>📊 Основная информация</h3>
                    <table class="modal-table">
                        <tr>
                            <td><strong>Тип сигнала:</strong></td>
                            <td>${formatSignalType(signal.signal_type)}</td>
                        </tr>
                        <tr>
                            <td><strong>Рынок:</strong></td>
                            <td>${signal.market_type || '-'}</td>
                        </tr>
                        <tr>
                            <td><strong>Статус:</strong></td>
                            <td>${isLive ? '🔴 Live' : '📅 Prematch'}</td>
                        </tr>
                        <tr>
                            <td><strong>Обнаружено:</strong></td>
                            <td>${signal.detected_at}</td>
                        </tr>
                    </table>
                </div>
                
                <div class="modal-card">
                    <h3>💰 Коэффициенты</h3>
                    <table class="modal-table">
                        <tr>
                            <td><strong>Betfair:</strong></td>
                            <td class="odds-big">${signal.betfair_odd ? signal.betfair_odd.toFixed(2) : '-'}</td>
                        </tr>
                        ${signal.bookmaker_odd ? `
                        <tr>
                            <td><strong>${signal.bookmaker_name || 'Букмекер'}:</strong></td>
                            <td class="odds-big">${signal.bookmaker_odd.toFixed(2)}</td>
                        </tr>
                        ` : ''}
                        ${signal.old_odd && signal.new_odd ? `
                        <tr>
                            <td><strong>Изменение:</strong></td>
                            <td>
                                <span class="odds-change">
                                    ${signal.old_odd.toFixed(2)} → ${signal.new_odd.toFixed(2)}
                                    <span class="drop-percent">${signal.odd_drop_percent.toFixed(1)}%</span>
                                </span>
                            </td>
                        </tr>
                        ` : ''}
                    </table>
                </div>
                
                <div class="modal-card">
                    <h3>💵 Денежный поток</h3>
                    <table class="modal-table">
                        <tr>
                            <td><strong>Залив:</strong></td>
                            <td class="money-big">€${signal.money_volume ? signal.money_volume.toLocaleString() : '-'}</td>
                        </tr>
                        ${signal.total_market_volume ? `
                        <tr>
                            <td><strong>Весь рынок:</strong></td>
                            <td>€${signal.total_market_volume.toLocaleString()}</td>
                        </tr>
                        ` : ''}
                        ${signal.flow_percent ? `
                        <tr>
                            <td><strong>Перекос:</strong></td>
                            <td><span class="flow-big ${signal.flow_percent > 80 ? 'flow-high' : ''}">${signal.flow_percent.toFixed(1)}%</span></td>
                        </tr>
                        ` : ''}
                    </table>
                </div>
                
                ${data.history && data.history.length > 1 ? `
                <div class="modal-card modal-full-width">
                    <h3>📈 История сигналов</h3>
                    <div class="history-timeline">
                        ${data.history.slice(0, 10).map(h => `
                            <div class="history-item">
                                <div class="history-time">${h.detected_at}</div>
                                <div class="history-badge">${formatSignalType(h.signal_type)}</div>
                                <div class="history-details">
                                    ${h.market_type || '-'} | 
                                    ${h.betfair_odd ? h.betfair_odd.toFixed(2) : '-'} | 
                                    €${h.money_volume ? h.money_volume.toLocaleString() : '-'}
                                    ${h.flow_percent ? ' | ' + h.flow_percent.toFixed(1) + '%' : ''}
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
                ` : ''}
                
                ${data.markets_22bet ? `
                <div class="modal-card modal-full-width">
                    <h3>🎲 Рынки на 22bet</h3>
                    <div class="markets-grid">
                        <div class="market-item">
                            <div class="market-label">П1</div>
                            <div class="market-odd">${data.markets_22bet.odd_1 || '-'}</div>
                        </div>
                        <div class="market-item">
                            <div class="market-label">X</div>
                            <div class="market-odd">${data.markets_22bet.odd_x || '-'}</div>
                        </div>
                        <div class="market-item">
                            <div class="market-label">П2</div>
                            <div class="market-odd">${data.markets_22bet.odd_2 || '-'}</div>
                        </div>
                        ${data.markets_22bet.total_over ? `
                        <div class="market-item">
                            <div class="market-label">ТБ</div>
                            <div class="market-odd">${data.markets_22bet.total_over}</div>
                        </div>
                        ` : ''}
                        ${data.markets_22bet.total_under ? `
                        <div class="market-item">
                            <div class="market-label">ТМ</div>
                            <div class="market-odd">${data.markets_22bet.total_under}</div>
                        </div>
                        ` : ''}
                    </div>
                </div>
                ` : ''}
            </div>
        `;
        
        modalBody.innerHTML = html;
        
    } catch (error) {
        console.error('Error loading signal details:', error);
        modalBody.innerHTML = `
            <h2>Ошибка загрузки</h2>
            <p>❌ Не удалось загрузить детали сигнала</p>
        `;
    }
}

// Закрытие модального окна
document.addEventListener('click', function(event) {
    const modal = document.getElementById('match-modal');
    const modalClose = document.querySelector('.modal-close');
    
    if (event.target === modal || event.target === modalClose) {
        modal.style.display = 'none';
    }
});

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

function updateLastUpdate() {
    const now = new Date();
    document.getElementById('last-update').textContent = now.toLocaleTimeString('ru-RU');
}
