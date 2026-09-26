import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import { test, before, after } from "node:test";
import { chromium } from "playwright";

const origin = "http://127.0.0.1:5181";
let server, browser;
before(async () => {
  server = spawn("./node_modules/.bin/vite", ["--host", "127.0.0.1", "--port", "5181", "--strictPort"], { stdio: "inherit" });
  for (let i = 0; i < 70; i++) {
    try { if ((await fetch(origin)).ok) break; } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); server?.kill(); });

for (const connected of [false, true]) {
  test(`startup status ${connected}: one probe and no console/network errors`, async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    const errors = [], failedRequests = [], badResponses = [], probes = [];
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("requestfailed", (request) => failedRequests.push(request.url()));
    page.on("response", (response) => { if (response.status() >= 400) badResponses.push(response.status()); });
    page.on("request", (request) => { if (new URL(request.url()).pathname === "/api/meta/test") probes.push(request); });
    await context.route("**/api/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      const id = "00000000-0000-4000-8000-000000000001";
      const json = path === "/api/meta/test" ? { connected }
        : path === "/api/meta/sync" ? { job_id: id }
        : path.startsWith("/api/meta/jobs/") ? { id, kind: "sync", state: "completed", counts: {}, items: [], next_cursor: null }
        : { items: [], next_cursor: null };
      return route.fulfill({ json });
    });
    try {
      await page.goto(origin);
      await page.getByText(connected ? "Meta connected successfully." : "Meta is not connected.", { exact: true }).waitFor();
      await page.waitForTimeout(100);
      assert.equal(probes.length, 1);
      assert.deepEqual(errors, []);
      assert.deepEqual(failedRequests, []);
      assert.deepEqual(badResponses, []);
    } finally { await context.close(); }
  });
}

for (const status of [401, 403, 502, 503]) {
  test(`status probe ${status} remains an error instead of disconnected`, async () => {
    const context = await browser.newContext();
    await context.route("**/api/meta/test", (route) => route.fulfill({ status, json: { detail: "Failure" } }));
    const page = await context.newPage();
    try {
      await page.goto(origin);
      await page.getByText("Meta connection could not be confirmed.", { exact: true }).waitFor();
      await page.getByRole("alert").getByText("Could not check the Meta connection. Try connecting again.", { exact: true }).waitFor();
    } finally { await context.close(); }
  });
}
