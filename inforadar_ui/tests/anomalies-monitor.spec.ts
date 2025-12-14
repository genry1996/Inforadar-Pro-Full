import { test, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

// Load mock data
const dataDir = path.join(__dirname, '../test-data');
const anomaliesDrop = JSON.parse(
  fs.readFileSync(path.join(dataDir, 'anomalies-drop.json'), 'utf-8')
);
const anomaliesCorridors = JSON.parse(
  fs.readFileSync(path.join(dataDir, 'anomalies-corridors.json'), 'utf-8')
);
const anomaliesLimitCuts = JSON.parse(
  fs.readFileSync(path.join(dataDir, 'anomalies-limit-cuts.json'), 'utf-8')
);
const anomaliesMixed = JSON.parse(
  fs.readFileSync(path.join(dataDir, 'anomalies-mixed.json'), 'utf-8')
);

test.describe('Betting Anomalies Monitor - Core Functionality', () => {
  
  test.beforeEach(async ({ page }) => {
    // Mock API endpoint - default to drops
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(anomaliesDrop)
      });
    });
  });

  test('should load and display test data', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    await page.waitForSelector('table tbody tr');
    
    const rows = await page.locator('table tbody tr').count();
    expect(rows).toBeGreaterThan(0);
    
    // Check that anomaly type icon is displayed
    const icon = page.locator('.anomaly-icon');
    await expect(icon).toBeVisible();
  });

  test('should display status badge as Live', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    const badge = page.locator('.status-badge');
    await expect(badge).toBeVisible();
    await expect(badge).toContainText('Live');
  });

  test('should calculate and display stats', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    await page.waitForSelector('#statsTotal');
    
    const total = await page.locator('#statsTotal').textContent();
    expect(parseInt(total || '0')).toBeGreaterThan(0);
  });
});

test.describe('Betting Anomalies Monitor - Filter by Anomaly Type', () => {
  
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesCorridors)
      });
    });
  });

  test('should show CORRIDOR filters when type is selected', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    // Uncheck ODDS_DROP
    await page.uncheck('#anom_odds_drop');
    // Check CORRIDOR
    await page.check('#anom_corridor');
    
    // Corridor filters should appear
    const corridorFilters = page.locator('#corridorFilters');
    await expect(corridorFilters).toBeVisible();
  });

  test('should adjust corridor width slider', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    await page.uncheck('#anom_odds_drop');
    await page.check('#anom_corridor');
    
    const slider = page.locator('#corridorWidth');
    await slider.fill('25');
    
    const value = await page.locator('#corridorWidthValue').textContent();
    expect(value).toContain('25%');
  });

  test('should show comparison filters for VALUEBETDIFF', async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesMixed)
      });
    });

    await page.goto('http://localhost:5000/anomalies_22bet');
    
    await page.uncheck('#anom_odds_drop');
    await page.check('#anom_valuebetdiff');
    
    const comparisonFilters = page.locator('#comparisonFilters');
    await expect(comparisonFilters).toBeVisible();
  });
});

test.describe('Betting Anomalies Monitor - League Selection', () => {
  
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesMixed)
      });
    });
  });

  test('should show league grid when sport is selected', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    await page.selectOption('#filterSport', 'football');
    
    const leagueGrid = page.locator('#leagueGridContainer');
    await expect(leagueGrid).toBeVisible();
    
    const leagues = await page.locator('.league-card').count();
    expect(leagues).toBeGreaterThan(0);
  });

  test('should select and highlight league card', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    await page.selectOption('#filterSport', 'football');
    await page.waitForSelector('.league-card');
    
    const firstCard = page.locator('.league-card').first();
    await firstCard.click();
    
    await expect(firstCard).toHaveClass(/selected/);
  });

  test('should deselect league when clicked again', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    await page.selectOption('#filterSport', 'tennis');
    await page.waitForSelector('.league-card');
    
    const firstCard = page.locator('.league-card').first();
    await firstCard.click();
    await expect(firstCard).toHaveClass(/selected/);
    
    await firstCard.click();
    await expect(firstCard).not.toHaveClass(/selected/);
  });
});

test.describe('Betting Anomalies Monitor - Accordion Toggles', () => {
  
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesDrop)
      });
    });
  });

  test('should toggle filter accordion sections', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    const firstHeader = page.locator('.filter-accordion-header').first();
    await firstHeader.click();
    
    const firstBody = page.locator('.filter-accordion-body').first();
    await expect(firstBody).toHaveClass(/active/);
    
    await firstHeader.click();
    await expect(firstBody).not.toHaveClass(/active/);
  });
});

test.describe('Betting Anomalies Monitor - Detail Modal', () => {
  
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesDrop)
      });
    });
  });

  test('should open detail modal when View button clicked', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    const viewBtn = page.locator('button:has-text("View")').first();
    await viewBtn.click();
    
    const modal = page.locator('#detailModal');
    await expect(modal).toHaveClass(/active/);
  });

  test('should close modal when close button clicked', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    const viewBtn = page.locator('button:has-text("View")').first();
    await viewBtn.click();
    
    const closeBtn = page.locator('#btnCloseModal');
    await closeBtn.click();
    
    const modal = page.locator('#detailModal');
    await expect(modal).not.toHaveClass(/active/);
  });

  test('should close modal when clicking outside', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    const viewBtn = page.locator('button:has-text("View")').first();
    await viewBtn.click();
    
    // Click on modal background
    await page.locator('#detailModal').click({ position: { x: 0, y: 0 } });
    
    const modal = page.locator('#detailModal');
    await expect(modal).not.toHaveClass(/active/);
  });

  test('should display all anomaly details in modal', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    const viewBtn = page.locator('button:has-text("View")').first();
    await viewBtn.click();
    
    // Check that modal fields are visible
    await expect(page.locator('.modal-field-label')).toHaveCount(10);
  });
});

test.describe('Betting Anomalies Monitor - Apply/Reset Filters', () => {
  
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesMixed)
      });
    });
  });

  test('should apply filters and show message', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    await page.fill('#filterChangePct', '10');
    await page.click('#btnApplyFilters');
    
    // Success message should appear
    await page.waitForSelector('.success-message', { timeout: 5000 });
    const message = page.locator('.success-message');
    await expect(message).toContainText('anomalies');
  });

  test('should reset filters to default state', async ({ page }) => {
    await page.goto('http://localhost:5000/anomalies_22bet');
    
    // Change some filters
    await page.fill('#filterChangePct', '15');
    await page.selectOption('#filterSeverity', 'critical');
    
    // Reset
    await page.click('#btnResetFilters');
    
    // Check that values are reset
    const changePct = await page.inputValue('#filterChangePct');
    expect(changePct).toBe('5');
    
    const severity = await page.inputValue('#filterSeverity');
    expect(severity).toBe('');
  });
});

test.describe('Betting Anomalies Monitor - Multiple Mock Data Sets', () => {
  
  test('should handle ODDS_DROP data', async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesDrop)
      });
    });

    await page.goto('http://localhost:5000/anomalies_22bet');
    await page.waitForSelector('table tbody tr');
    
    const anomalyType = await page.locator('.anomaly-icon').first().getAttribute('title');
    expect(anomalyType).toBe('ODDS_DROP');
  });

  test('should handle CORRIDOR data', async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesCorridors)
      });
    });

    await page.goto('http://localhost:5000/anomalies_22bet');
    await page.waitForSelector('table tbody tr');
    
    const anomalyType = await page.locator('.anomaly-icon').first().getAttribute('title');
    expect(anomalyType).toBe('CORRIDOR');
  });

  test('should handle LIMIT_CUT data with critical severity', async ({ page }) => {
    await page.route('**/api/anomalies/test', route => {
      route.fulfill({
        status: 200,
        body: JSON.stringify(anomaliesLimitCuts)
      });
    });

    await page.goto('http://localhost:5000/anomalies_22bet');
    await page.waitForSelector('table tbody tr');
    
    const severity = await page.locator('.severity-critical').first().textContent();
    expect(severity).toContain('CRITICAL');
  });
});