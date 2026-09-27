import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test, before, after } from 'node:test';
import { build, preview } from 'vite';
import { chromium } from 'playwright';
const routes = [['/privacy', 'Privacy Policy', 'Privacy Policy'], ['/terms', 'Terms of Service', 'Terms of Service'], ['/data-deletion', 'Data Deletion Instructions', 'Data Deletion']];
let server, browser, origin, directory;
before(async () => {
  // Always test a fresh production bundle, including when invoked on its own.
  directory = await mkdtemp(join(tmpdir(), 'contentmetric-legal-'));
  if (process.env.V5_SCREENSHOT_DIR) await mkdir(process.env.V5_SCREENSHOT_DIR, { recursive: true });
  await build({ build: { outDir: directory, emptyOutDir: true }, logLevel: 'error' });
  server = await preview({ build: { outDir: directory }, preview: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
  origin = server.resolvedUrls.local[0]; browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
  if (server) await new Promise(resolve => server.httpServer.close(resolve));
  if (directory) await rm(directory, { recursive: true, force: true });
});
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
      for (const width of [1440, 1280, 1024, 768, 390, 375, 320]) {
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
        if (process.env.V5_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.V5_SCREENSHOT_DIR}/${route.slice(1)}-${width}.png`, fullPage: true });
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
      await page.getByRole('heading', { name: 'Welcome back', exact: true }).waitFor();
      assert.equal(new URL(page.url()).pathname, '/login'); assert.equal(await page.title(), 'ContentMetric');
      await page.getByRole('navigation', { name: 'Legal', exact: true }).getByRole('link', { name: 'Privacy', exact: true }).click();
      await page.getByRole('heading', { name: 'Privacy Policy', exact: true }).waitFor();
    } finally { await context.close(); }
  });
}
