import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test, before, after } from 'node:test';
import { preview } from 'vite';
import { chromium } from 'playwright';
const routes = [['/privacy', 'Privacy Policy', 'Privacy Policy'], ['/terms', 'Terms of Service', 'Terms of Service'], ['/data-deletion', 'Data Deletion Instructions', 'Data Deletion']];
let server, browser, origin;
before(async () => {
  // Test the production bundle; build before running this suite.
  server = await preview({ preview: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  origin = server.resolvedUrls.local[0]; browser = await chromium.launch();
});
after(async () => { await browser?.close(); await new Promise(resolve => server?.httpServer.close(resolve)); });
test('Vercel preserves API proxy precedence and serves all legal routes', async () => {
  const { rewrites } = JSON.parse(await readFile('vercel.json', 'utf8'));
  assert.deepEqual(rewrites[0], { source: '/api/:path*', destination: 'https://video-analyser-1ek5.onrender.com/api/:path*' });
  for (const [route] of routes) assert.deepEqual(rewrites.find(rule => rule.source === route), { source: route, destination: '/index.html' });
});
for (const [route, heading, title] of routes) {
  test(`${route}: public load, refresh, titles, no API, responsive layout and keyboard navigation`, async () => {
    const context = await browser.newContext(); const calls = [], errors = [];
    await context.route('**/*', request => {
      const url = new URL(request.request().url());
      if (url.pathname.startsWith('/api/') || url.origin !== new URL(origin).origin) { calls.push(url.href); return request.abort(); }
      return request.continue();
    });
    const page = await context.newPage(); page.on('pageerror', error => errors.push(error.message));
    try {
      for (const width of [1280, 375, 320]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(`${origin}${route.slice(1)}`, { waitUntil: 'networkidle' });
        await page.getByRole('heading', { level: 1, name: heading, exact: true }).waitFor();
        assert.equal(await page.title(), `${title} | ContentMetric`);
        assert.equal(await page.getByRole('main').count(), 1);
        assert.equal(await page.getByRole('navigation', { name: 'Company', exact: true }).count(), 0);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        const text = await page.locator('main').innerText();
        assert.match(text, /Last updated: 27 September 2026/);
        assert.doesNotMatch(text, /Video Analy[sz]er|\[PLACEHOLDER\]|ContentMetric Ltd|GDPR certified|100% secure/);
      }
      await page.reload({ waitUntil: 'networkidle' });
      assert.equal(await page.title(), `${title} | ContentMetric`);
      await page.keyboard.press('Tab');
      assert.equal(await page.evaluate(() => document.activeElement?.textContent), 'Back to ContentMetric');
      assert.equal(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'solid');
      const count = await page.locator('a').count();
      for (let i = 1; i < count; i++) { await page.keyboard.press('Tab'); assert.equal(await page.evaluate(() => document.activeElement?.tagName), 'A'); }
      const footer = page.getByRole('navigation', { name: 'Legal', exact: true });
      for (const [target, targetHeading, targetTitle] of routes) {
        await footer.locator(`a[href="${target}"]`).click();
        await page.getByRole('heading', { name: targetHeading, exact: true }).waitFor();
        assert.equal(await page.title(), `${targetTitle} | ContentMetric`);
      }
      assert.deepEqual(calls, []); assert.deepEqual(errors, []);
      await page.getByRole('link', { name: 'Back to ContentMetric', exact: true }).click();
      await page.getByRole('heading', { name: 'Overview', exact: true }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/'); assert.equal(await page.title(), 'ContentMetric');
      await page.getByRole('navigation', { name: 'Legal', exact: true }).getByRole('link', { name: 'Privacy', exact: true }).click();
      await page.getByRole('heading', { name: 'Privacy Policy', exact: true }).waitFor();
    } finally { await context.close(); }
  });
}
