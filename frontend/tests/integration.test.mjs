import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright";

const origin = "http://127.0.0.1:5178";
async function waitForServer(url, child, timeout = 45000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (child.exitCode !== null) throw new Error(`Test server exited: ${child.exitCode}`);
    try { if ((await fetch(url)).ok) return; } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Test server did not start: ${url}`);
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Test server did not stop cleanly")), 20000);
    child.once("exit", (code) => { clearTimeout(timer); code === 0 || code === null || code === 143 ? resolve() : reject(new Error(`Test server exited ${code}`)); });
    child.kill("SIGTERM");
  });
}

test("browser → real FastAPI → workers/analysis → PostgreSQL → multi-video recommendation", { timeout: 180000 }, async () => {
  assert.ok(process.env.TEST_DATABASE_URL, "Set TEST_DATABASE_URL to disposable PostgreSQL; this test must not silently skip");
  const directory = await mkdtemp(join(tmpdir(), "meta-browser-integration-"));
  let backend, vite, browser;
  const calls = [], failures = [];
  try {
    backend = spawn(".venv/bin/python", ["tests/frontend_integration_server.py"], {
      cwd: "../backend", env: { ...process.env, META_E2E_DIRECTORY: directory, META_E2E_PORT: "8061" }, stdio: "inherit",
    });
    await waitForServer("http://127.0.0.1:8061/health", backend);
    vite = spawn("./node_modules/.bin/vite", ["--config", "tests/integration.vite.mjs"], { stdio: "inherit" });
    await waitForServer(origin, vite);
    const session = JSON.parse(await readFile(join(directory, "session.json"), "utf8"));
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext();
    // A real backend-issued session, scoped to the same route as the production cookie.
    await context.addCookies([{ ...session, domain: "127.0.0.1", path: "/api/meta", httpOnly: true, secure: true, sameSite: "Lax" }]);
    const page = await context.newPage(); page.setDefaultTimeout(60000);
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (path.startsWith("/api/")) calls.push({ path, method: request.method(), body: request.postDataJSON() });
    });
    page.on("pageerror", (error) => failures.push(error.message));
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) failures.push(`${response.status()} ${new URL(response.url()).pathname}`);
    });
    // No page.route / context.route: all application requests reach the real server.
    await page.goto(origin);
    await page.getByRole("checkbox", { name: "Select Facebook video", exact: true }).waitFor();
    await page.waitForFunction(() => {
      const cards = [...document.querySelectorAll(".video-card")];
      return ["Facebook video", "IG Reel", "Video ad"].every((name) => cards.some((card) => card.querySelector("h3")?.textContent === name && card.querySelector(".status")?.textContent === "Ready"));
    }, null, { timeout: 90000 });
    const history = page.getByRole("checkbox", { name: "Select History", exact: true });
    await history.check();
    await page.waitForFunction(() => [...document.querySelectorAll(".video-card")].some((card) => card.querySelector("h3")?.textContent === "History" && card.querySelector(".status")?.textContent === "Ready"));
    await page.getByRole("checkbox", { name: "Select Facebook video", exact: true }).check();
    await page.getByRole("checkbox", { name: "Select IG Reel", exact: true }).check();
    await page.getByRole("checkbox", { name: "Select Video ad", exact: true }).check();
    await page.getByRole("button", { name: "Generate a new video idea", exact: true }).click();
    await page.getByText("Based on 4 selected videos.").waitFor();
    await page.getByText("Show how your business solves a real customer problem.", { exact: true }).waitFor();
    assert.match(await page.locator(".script").innerText(), /Demonstrate the process/);
    const recommendation = calls.find((call) => call.path === "/api/meta/recommendations");
    assert.equal(recommendation.body.video_ids.length, 4);
    assert.equal(new Set(recommendation.body.video_ids).size, 4);
    assert.equal(calls.find((call) => call.path === "/api/meta/sync").body, null);
    assert.equal(calls.find((call) => call.path === "/api/meta/library/analyze").body.item_ids.length, 1);
    assert.equal(calls.some((call) => call.path.startsWith("/api/meta/jobs/")), true);
    assert.equal(calls.some((call) => call.path === "/api/meta/library/recommendations" || call.path === "/api/meta/library/sync" || call.path.startsWith("/api/meta/discovery")), false);
    // A second request must reuse stored analysis, not queue another import.
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/api/meta/recommendations") && response.status() === 200),
      page.getByRole("button", { name: "Generate a new video idea", exact: true }).click(),
    ]);
    assert.equal(calls.filter((call) => call.path === "/api/meta/library/analyze").length, 1);
    const unauthorized = await browser.newContext();
    assert.equal((await unauthorized.request.get(`${origin}/api/meta/library`)).status(), 401);
    await unauthorized.close();
    assert.deepEqual(failures, []);
    await page.setViewportSize({ width: 320, height: 900 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: "/tmp/meta-real-fastapi-320.png", fullPage: true });
    await browser.close(); browser = null;
    await stop(vite); vite = null;
    await stop(backend); backend = null;
    const report = JSON.parse(await readFile(join(directory, "report.json"), "utf8"));
    assert.equal(report.stored_videos, 5);
    assert.equal(report.analysis_calls.length, 5);
    assert.ok(report.analysis_calls.every((call) => call.duration === 4 && call.scene_count >= 2));
    assert.equal(report.provider_inputs.length, 2);
    for (const evidence of report.provider_inputs) {
      assert.equal(evidence.videos.length, 4);
      assert.ok(evidence.videos.every((entry) => entry.on_screen_text.some((row) => row.text.includes("VIDEO TEST"))));
      assert.equal(new Set(evidence.performance_snapshots.map((entry) => entry.item_id)).size, evidence.performance_snapshots.length);
    }
  } finally {
    await browser?.close();
    await stop(vite);
    await stop(backend);
    await rm(directory, { recursive: true, force: true });
  }
});
