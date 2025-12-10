// =====================================================
// 22BET PARSER - Node.js + Puppeteer + Stealth
// =====================================================
// !! ВАЖНО: 22bet активно блокирует ботов !!
// Используем puppeteer-extra с stealth плагином

// npm install puppeteer puppeteer-extra puppeteer-extra-plugin-stealth

const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
puppeteer.use(StealthPlugin());

const fs = require('fs');
const path = require('path');

// Логирование
const logger = {
  info: (msg) => console.log(`[INFO] ${new Date().toISOString()}: ${msg}`),
  error: (msg) => console.error(`[ERROR] ${new Date().toISOString()}: ${msg}`),
  warn: (msg) => console.warn(`[WARN] ${new Date().toISOString()}: ${msg}`),
};

class BetParser {
  constructor(options = {}) {
    this.options = {
      headless: true,
      timeout: 15000,
      retries: 3,
      delays: {
        betweenRequests: 2000,  // 2 сек между запросами
        pageLoad: 3000,         // 3 сек ждём загрузку
      },
      ...options,
    };
    
    this.browser = null;
    this.page = null;
    this.bookmaker = '22bet';
    this.baseUrl = 'https://22bet.com';
  }

  /**
   * Инициализировать браузер
   */
  async init() {
    try {
      logger.info('Инициализация браузера...');
      
      this.browser = await puppeteer.launch({
        headless: this.options.headless,
        args: [
          '--no-sandbox',
          '--disable-setuid-sandbox',
          '--disable-dev-shm-usage',
          '--disable-blink-features=AutomationControlled',
        ],
      });
      
      this.page = await this.browser.newPage();
      
      // Эмулируем реального пользователя
      await this.page.setUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
      );
      
      // Дополнительные заголовки
      await this.page.setExtraHTTPHeaders({
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Referer': this.baseUrl,
      });
      
      // Настройка viewport
      await this.page.setViewport({ width: 1920, height: 1080 });
      
      logger.info('✅ Браузер готов');
      return true;
    } catch (err) {
      logger.error(`Ошибка инициализации браузера: ${err.message}`);
      return false;
    }
  }

  /**
   * Закрыть браузер
   */
  async close() {
    try {
      if (this.browser) {
        await this.browser.close();
        logger.info('Браузер закрыт');
      }
    } catch (err) {
      logger.error(`Ошибка закрытия браузера: ${err.message}`);
    }
  }

  /**
   * Перейти на страницу (с повторами)
   */
  async navigateWithRetry(url) {
    for (let attempt = 1; attempt <= this.options.retries; attempt++) {
      try {
        logger.info(`Переход на ${url} (попытка ${attempt}/${this.options.retries})`);
        
        await this.page.goto(url, {
          waitUntil: 'networkidle2',
          timeout: this.options.timeout,
        });
        
        // Ждём загрузку контента
        await this.page.waitForTimeout(this.options.delays.pageLoad);
        
        logger.info('✅ Страница загружена');
        return true;
      } catch (err) {
        logger.warn(`Попытка ${attempt} не удалась: ${err.message}`);
        if (attempt < this.options.retries) {
          await this.page.waitForTimeout(2000);
        }
      }
    }
    return false;
  }

  /**
   * Получить список матчей (Футбол, Лайв)
   */
  async getLiveMatches() {
    try {
      logger.info('Получение лайв матчей...');
      
      // Переходим на страницу Лайва
      const success = await this.navigateWithRetry(`${this.baseUrl}/#/live`);
      if (!success) {
        throw new Error('Не удалось загрузить страницу Лайва');
      }
      
      // Кликаем на Футбол (если нужно)
      try {
        await this.page.click('a[href*="soccer"]');
        await this.page.waitForTimeout(2000);
      } catch (e) {
        logger.warn('Не найдена кнопка Футбола, продолжаем...');
      }
      
      // Ждём загрузки матчей
      await this.page.waitForSelector('[class*="match"]', { timeout: 5000 }).catch(() => {
        logger.warn('Селектор матчей не найден');
      });
      
      // Извлекаем данные через evaluate
      const matches = await this.page.evaluate(() => {
        const matchElements = Array.from(document.querySelectorAll('[class*="match"]'));
        
        return matchElements.map((el) => {
          try {
            // Парсим разные варианты структуры
            const homeTeam = el.querySelector('[class*="home"], [class*="team-1"]')?.innerText;
            const awayTeam = el.querySelector('[class*="away"], [class*="team-2"]')?.innerText;
            const matchTime = el.querySelector('[class*="time"]')?.innerText;
            
            // Коэффициенты (1X2)
            const odds1 = el.querySelector('[class*="odd-1"], [data-market="1"]')?.innerText;
            const oddsX = el.querySelector('[class*="odd-x"], [data-market="X"]')?.innerText;
            const odds2 = el.querySelector('[class*="odd-2"], [data-market="2"]')?.innerText;
            
            return {
              id: el.getAttribute('data-match-id') || Math.random().toString(36),
              homeTeam: homeTeam?.trim() || 'Unknown',
              awayTeam: awayTeam?.trim() || 'Unknown',
              time: matchTime?.trim() || 'Live',
              odds: {
                '1': parseFloat(odds1) || null,
                'X': parseFloat(oddsX) || null,
                '2': parseFloat(odds2) || null,
              },
              status: 'live',
            };
          } catch (e) {
            return null;
          }
        }).filter(m => m !== null);
      });
      
      logger.info(`✅ Получено ${matches.length} матчей`);
      return matches;
    } catch (err) {
      logger.error(`Ошибка получения матчей: ${err.message}`);
      return [];
    }
  }

  /**
   * Получить Прематч матчи
   */
  async getPrematchMatches(sport = 'soccer') {
    try {
      logger.info(`Получение Прематч матчей (${sport})...`);
      
      const success = await this.navigateWithRetry(`${this.baseUrl}/#/events/${sport}`);
      if (!success) {
        throw new Error(`Не удалось загрузить страницу ${sport}`);
      }
      
      // Ждём загрузки матчей
      await this.page.waitForSelector('[class*="match"], [class*="event"]', { timeout: 5000 }).catch(() => {});
      
      const matches = await this.page.evaluate(() => {
        const matchElements = Array.from(document.querySelectorAll('[class*="match"], [class*="event"]'));
        
        return matchElements.slice(0, 20).map((el) => {
          try {
            const homeTeam = el.querySelector('[class*="team-1"], [class*="home"]')?.innerText;
            const awayTeam = el.querySelector('[class*="team-2"], [class*="away"]')?.innerText;
            const time = el.querySelector('[class*="start-time"], [class*="date"]')?.innerText;
            
            const odds1 = el.querySelector('[data-odd="1"], [class*="odd-home"]')?.innerText;
            const oddsX = el.querySelector('[data-odd="X"], [class*="odd-draw"]')?.innerText;
            const odds2 = el.querySelector('[data-odd="2"], [class*="odd-away"]')?.innerText;
            
            return {
              id: el.getAttribute('data-match-id') || Math.random().toString(36),
              homeTeam: homeTeam?.trim() || 'Unknown',
              awayTeam: awayTeam?.trim() || 'Unknown',
              startTime: time?.trim() || 'TBD',
              odds: {
                '1': parseFloat(odds1) || null,
                'X': parseFloat(oddsX) || null,
                '2': parseFloat(odds2) || null,
              },
              status: 'prematch',
            };
          } catch (e) {
            return null;
          }
        }).filter(m => m !== null);
      });
      
      logger.info(`✅ Получено ${matches.length} матчей`);
      return matches;
    } catch (err) {
      logger.error(`Ошибка получения матчей: ${err.message}`);
      return [];
    }
  }

  /**
   * Обнаружить аномалии (сравнить с предыдущими данными)
   */
  detectAnomalies(currentMatches, previousMatches = {}) {
    const anomalies = [];
    
    for (const match of currentMatches) {
      const prev = previousMatches[match.id];
      
      if (!prev) continue;
      
      // Проверка падения коэффициентов
      for (const market of ['1', 'X', '2']) {
        const oldOdd = prev.odds?.[market];
        const newOdd = match.odds?.[market];
        
        if (oldOdd && newOdd && oldOdd > 0) {
          const change = ((newOdd - oldOdd) / oldOdd) * 100;
          
          // Аномалия: падение > 5%
          if (change < -5) {
            anomalies.push({
              type: 'sharp_drop',
              match: `${match.homeTeam} vs ${match.awayTeam}`,
              market,
              oldOdd,
              newOdd,
              changePercent: change.toFixed(2),
              timestamp: new Date().toISOString(),
            });
          }
          
          // Аномалия: рост > 5%
          if (change > 5) {
            anomalies.push({
              type: 'sharp_rise',
              match: `${match.homeTeam} vs ${match.awayTeam}`,
              market,
              oldOdd,
              newOdd,
              changePercent: change.toFixed(2),
              timestamp: new Date().toISOString(),
            });
          }
        }
      }
    }
    
    return anomalies;
  }

  /**
   * Основной цикл парсинга
   */
  async run(interval = 60000) {
    logger.info('🚀 Запуск парсера 22bet...');
    
    if (!await this.init()) {
      logger.error('Не удалось инициализировать браузер');
      return;
    }
    
    let previousMatches = {};
    
    try {
      while (true) {
        logger.info('------- ЦИКЛ ПАРСИНГА -------');
        
        // Получаем Лайв
        const liveMatches = await this.getLiveMatches();
        
        // Получаем Прематч
        const prematchMatches = await this.getPrematchMatches('soccer');
        
        const allMatches = [...liveMatches, ...prematchMatches];
        
        // Обнаруживаем аномалии
        const anomalies = this.detectAnomalies(allMatches, previousMatches);
        
        if (anomalies.length > 0) {
          logger.info(`🚨 Найдено ${anomalies.length} аномалий:`);
          anomalies.forEach(anom => {
            logger.info(`  - ${anom.type}: ${anom.match} (${anom.changePercent}%)`);
          });
          
          // Сохраняем аномалии в JSON для отправки в Telegram
          await this.saveAnomalies(anomalies);
        }
        
        // Сохраняем текущие матчи как "предыдущие"
        previousMatches = {};
        allMatches.forEach(m => {
          previousMatches[m.id] = m;
        });
        
        logger.info(`⏳ Ждём ${interval / 1000} секунд до следующего обновления...\n`);
        await new Promise(resolve => setTimeout(resolve, interval));
      }
    } catch (err) {
      logger.error(`Ошибка в основном цикле: ${err.message}`);
    } finally {
      await this.close();
    }
  }

  /**
   * Сохранить аномалии в файл
   */
  async saveAnomalies(anomalies) {
    try {
      const file = path.join(__dirname, 'anomalies.json');
      const data = {
        timestamp: new Date().toISOString(),
        bookmaker: this.bookmaker,
        count: anomalies.length,
        anomalies,
      };
      
      fs.writeFileSync(file, JSON.stringify(data, null, 2));
      logger.info(`✅ Аномалии сохранены в ${file}`);
    } catch (err) {
      logger.error(`Ошибка сохранения аномалий: ${err.message}`);
    }
  }
}

// =====================================================
// ЗАПУСК
// =====================================================

async function main() {
  const parser = new BetParser();
  
  // Запускаем с интервалом 60 секунд (1 минута)
  await parser.run(60000);
}

main().catch(err => {
  logger.error(`Критическая ошибка: ${err.message}`);
  process.exit(1);
});
