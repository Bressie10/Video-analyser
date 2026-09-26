import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import { test as nodeTest, before, after } from "node:test";
import { chromium } from "playwright";
const test = (name, run) => nodeTest(name, { timeout: 30000 }, run);
const origin = "http://127.0.0.1:5179";
let server, browser;
before(async () => {
  server = spawn("./node_modules/.bin/vite", ["--host", "127.0.0.1", "--port", "5179", "--strictPort"], { stdio: "inherit" });
  for (let i = 0; i < 70; i++) { try { if ((await fetch(origin)).ok) break; } catch {} await new Promise((resolve) => setTimeout(resolve, 100)); }
  browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); server?.kill(); });
const uuid = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const account = uuid(1000), jobId = uuid(9000);
const video = (n, changes = {}) => ({
  id: uuid(n), video_id: uuid(n), account_id: account, account_label: "Our business", account_platform: "facebook",
  platform: "facebook", content_type: "reel", label: `Business video ${n}`, published_at: "2026-09-20T12:00:00Z",
  analysis_state: "completed", analysis_version: 1, analysis_error: null, metrics_state: "completed", metrics_error: null,
  performance: [{ item_id: uuid(n), fetched_at: "2026-09-21T12:00:00Z", attribution: "organic", snapshot: { performance_source: "facebook", performance_metrics: { view_count: 120, like_count: 12, comment_count: null, share_count: 0 } } }], ...changes,
});
const job = (id = jobId, changes = {}) => ({ id, kind: "sync", state: "completed", counts: { completed: 2 }, items: [], next_cursor: null, created_at: "2026-09-20T12:00:00Z", finished_at: "2026-09-20T12:01:00Z", ...changes });
const select = (page, n) => page.getByRole("checkbox", { name: `Select Business video ${n}`, exact: true });
const generate = (page) => page.getByRole("button", { name: "Generate a new video idea", exact: true });
const loaded = (page) => select(page, 1).waitFor();
const generated = (page) => page.getByRole("heading", { name: "New video idea", exact: true }).waitFor();
async function withApp(options, run) {
  const context = await browser.newContext();
  const calls = [], errors = [];
  const items = options.items ?? [video(1), video(2)];
  let connected = options.connected ?? true;
  await context.route("https://meta-provider.test/authorize", (route) => route.fulfill({ contentType: "text/html", body: `<a href="${origin}/api/meta/callback?code=mock&state=mock">Continue with Meta</a>` }));
  await context.route("**/api/**", async (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    calls.push({ path, method: request.method(), body: request.postDataJSON(), headers: request.headers(), url });
    if (options.route && await options.route(route, url, calls)) return;
    if (path === "/api/meta/test") return route.fulfill({ status: 200, json: { connected } });
    if (path === "/api/meta/connect") return route.fulfill({ contentType: "text/html", body: '<script>location.href="https://meta-provider.test/authorize"</script>' });
    if (path === "/api/meta/callback") { connected = true; return route.fulfill({ json: { connected: true, job_id: jobId } }); }
    if (path === "/api/meta/library") return route.fulfill({ json: { items, next_cursor: null } });
    if (path === "/api/meta/sync") return route.fulfill({ status: 202, json: { job_id: jobId } });
    if (path.startsWith("/api/meta/jobs/")) return route.fulfill({ json: job(path.split("/").at(-1), { kind: path.endsWith(jobId) ? "sync" : "analysis" }) });
    if (path === "/api/meta/library/analyze") {
      for (const item of items.flatMap((item) => [item, ...(item.assets ?? [])])) if (request.postDataJSON().item_ids.includes(item.id)) { item.analysis_state = "completed"; item.video_id = item.id; item.analysis_version = 1; }
      return route.fulfill({ status: 202, json: { job_id: uuid(9001) } });
    }
    if (path === "/api/meta/recommendations") return route.fulfill({ json: { model: "private-model", response: options.response ?? "## Performance patterns and evidence\nLimited evidence.\n## Uncertainties\nSmall sample.\n## New video idea\nShow the story behind your service.\n## Script\nStart with a customer question.\nShow your process." } });
    return route.fulfill({ status: 404, json: { detail: "Unsupported route" } });
  });
  const page = await context.newPage(); page.setDefaultTimeout(8000);
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await page.goto(origin); await run(page, calls, context);
    assert.deepEqual(errors, []);
    assert.equal(calls.some((call) => call.path.includes("/discovery/") || call.path === "/api/meta/library/sync" || call.path === "/api/meta/library/recommendations" || call.path === "/api/videos"), false);
    assert.equal(calls.some((call) => call.url.searchParams.has("sources")), false);
  } finally { await context.close(); }
}
async function connect(page) {
  const popupPromise = page.waitForEvent("popup"); await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
  await (await popupPromise).getByRole("link", { name: "Continue with Meta" }).click();
  await page.getByText("Meta connected successfully.").waitFor();
}

test("existing session loads the real library shape and bodyless sync", async () => {
  await withApp({}, async (page, calls) => {
    await loaded(page); assert.equal(await page.getByRole("checkbox", { name: "Our business", exact: true }).isChecked(), true);
    assert.equal(calls.find((call) => call.path === "/api/meta/sync").body, null);
    assert.equal(calls.some((call) => call.path === `/api/meta/jobs/${jobId}`), true);
    assert.equal(calls.find((call) => call.path === "/api/meta/library").url.searchParams.get("limit"), "100");
  });
});
test("popup login resumes callback job instead of starting another sync", async () => {
  await withApp({ connected: false }, async (page, calls) => {
    await connect(page); await loaded(page);
    assert.equal(calls.some((call) => call.path === `/api/meta/jobs/${jobId}`), true);
    assert.equal(calls.some((call) => call.path === "/api/meta/sync"), false);
    await page.getByRole("button", { name: "Sync content", exact: true }).click();
    await page.waitForResponse((response) => response.url().endsWith("/api/meta/sync"));
  });
});
test("one and multiple ready videos send video_ids and render text sections", async () => {
  await withApp({}, async (page, calls) => {
    await loaded(page); assert.equal(await generate(page).isDisabled(), true);
    await select(page, 1).check(); await generate(page).click(); await generated(page);
    assert.deepEqual(calls.find((call) => call.path.endsWith("/recommendations")).body, { video_ids: [uuid(1)] });
    await select(page, 2).check(); await generate(page).click(); await page.getByText("Based on 2 selected videos.").waitFor();
    assert.deepEqual(calls.filter((call) => call.path.endsWith("/recommendations")).at(-1).body, { video_ids: [uuid(1), uuid(2)] });
    assert.match(await page.locator(".script").innerText(), /Show your process/);
    assert.doesNotMatch(await page.locator(".idea-result").innerText(), /private-model|Limited evidence/);
  });
});
test("multi-select supports individual deselect and clear", async () => {
  await withApp({}, async (page) => {
    await loaded(page); await page.getByRole("button", { name: "Select all currently shown" }).click();
    await page.getByText("2 selected", { exact: true }).waitFor(); await select(page, 1).uncheck();
    await page.getByText("1 selected", { exact: true }).waitFor(); await page.getByRole("button", { name: "Clear selection" }).click();
    assert.equal(await select(page, 2).isChecked(), false); assert.equal(await generate(page).isDisabled(), true);
  });
});
test("same-named accounts stay distinct and changing filters does not sync", async () => {
  await withApp({ items: [video(1), video(2, { account_id: uuid(1001) })] }, async (page, calls) => {
    await page.getByRole("checkbox", { name: "Our business (1)" }).waitFor();
    assert.equal(await select(page, 1).count(), 0);
    const syncs = calls.filter((call) => call.path === "/api/meta/sync").length;
    await page.getByRole("checkbox", { name: "Our business (1)" }).check(); await loaded(page); await select(page, 1).check();
    await page.getByRole("checkbox", { name: "Our business (2)" }).check(); assert.equal(await select(page, 1).isChecked(), false);
    assert.equal(calls.filter((call) => call.path === "/api/meta/sync").length, syncs);
  });
});
test("account auto-selection waits for all real cursor pages", async () => {
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    const second = url.searchParams.has("after");
    await route.fulfill({ json: { items: [video(second ? 2 : 1, second ? { account_id: uuid(1001), account_label: "Second shop" } : {})], next_cursor: second ? null : uuid(1) } }); return true;
  } }, async (page) => {
    await page.getByRole("checkbox", { name: "Second shop" }).waitFor(); assert.equal(await page.getByRole("checkbox", { name: "Our business", exact: true }).isChecked(), false);
  });
});
test("mixed platforms and an ad deduplicate shared video assets", async () => {
  const organic = video(1), other = video(2, { account_id: uuid(2000), account_label: "Our Instagram", account_platform: "instagram", platform: "instagram" });
  const ad = video(3, { video_id: null, account_id: uuid(3000), account_platform: "meta_ads", account_label: "Our ads", platform: "meta_ads", content_type: "ad", assets: [organic], analysis_state: "completed", performance: [] });
  await withApp({ items: [organic, other, ad] }, async (page, calls) => {
    await loaded(page); await page.getByText("Paid ad", { exact: true }).waitFor(); await page.getByText("Instagram Reel", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Select all currently shown" }).click(); await generate(page).click(); await generated(page);
    assert.deepEqual(calls.find((call) => call.path.endsWith("/recommendations")).body.video_ids, [uuid(1), uuid(2)]);
  });
});
test("ad-only assets are not duplicate organic cards and shared-ad counts are not summed", async () => {
  const asset = video(1, { account_id: uuid(3000), account_platform: "meta_ads", account_label: "Our ads" });
  const ad = video(3, { account_id: uuid(3000), account_platform: "meta_ads", account_label: "Our ads", platform: "meta_ads", content_type: "ad", assets: [asset, { ...asset, id: uuid(2), video_id: uuid(2) }], performance: [{ item_id: uuid(3), fetched_at: "2026-09-20", attribution: "shared_ad", snapshot: { performance_source: "meta_ads", performance_metrics: { view_count: 120 } } }] });
  await withApp({ items: [asset, ad] }, async (page) => {
    await select(page, 3).waitFor(); assert.equal(await select(page, 1).count(), 0);
    await page.getByText("Performance describes the whole ad, not individual videos.").waitFor();
    assert.equal(await page.locator(".metrics dd").innerText(), "120");
  });
});
test("deferred selection automatically prepares using item_ids", async () => {
  const item = video(1, { analysis_state: "deferred", video_id: null, analysis_version: null });
  await withApp({ items: [item] }, async (page, calls) => {
    await loaded(page); await page.getByText("New", { exact: true }).waitFor(); await select(page, 1).check();
    await page.getByText("Ready", { exact: true }).waitFor();
    assert.deepEqual(calls.find((call) => call.path === "/api/meta/library/analyze").body, { item_ids: [uuid(1)] });
    assert.equal(await generate(page).isEnabled(), true);
  });
});
test("processing is polled until ready without losing selection", async () => {
  const item = video(1, { analysis_state: "processing", video_id: null });
  await withApp({ items: [item] }, async (page, calls) => {
    await loaded(page); await select(page, 1).check(); assert.equal(await generate(page).isDisabled(), true);
    item.analysis_state = "completed"; item.video_id = item.id;
    await page.getByText("Ready", { exact: true }).waitFor({ timeout: 12000 }); assert.equal(await select(page, 1).isChecked(), true);
    assert.equal(calls.some((call) => call.path === "/api/meta/library/analyze"), false);
  });
});
test("ready content is usable while sync is running", async () => {
  await withApp({ route: async (route, url) => {
    if (!url.pathname.startsWith("/api/meta/jobs/")) return false;
    await route.fulfill({ json: job(jobId, { state: "running", finished_at: null }) }); return true;
  } }, async (page) => { await loaded(page); await select(page, 1).check(); assert.equal(await generate(page).isEnabled(), true); });
});
test("partly ready ad keeps its usable assets selectable", async () => {
  await withApp({ items: [video(3, { account_platform: "meta_ads", content_type: "ad", analysis_state: "failed", assets: [video(1), video(2, { analysis_state: "unavailable", video_id: null })] })] }, async (page, calls) => {
    await select(page, 3).waitFor(); await page.getByText("Partly ready", { exact: true }).waitFor(); await select(page, 3).check();
    await generate(page).click(); await generated(page); assert.deepEqual(calls.find((call) => call.path.endsWith("/recommendations")).body.video_ids, [uuid(1)]);
  });
});
test("failed, unavailable and unsupported items cannot be selected", async () => {
  await withApp({ items: [video(1), ...["failed", "unavailable", "unsupported"].map((state, i) => video(i + 2, { analysis_state: state, video_id: null }))] }, async (page) => {
    await loaded(page); for (const n of [2, 3, 4]) assert.equal(await select(page, n).isDisabled(), true);
    await page.getByRole("button", { name: "Select all currently shown" }).click(); await page.getByText("1 selected", { exact: true }).waitFor();
  });
});
test("large selection is retained but generation enforces the actual 20-video limit", async () => {
  await withApp({ items: Array.from({ length: 26 }, (_, i) => video(i + 1)) }, async (page, calls) => {
    await loaded(page); await page.getByRole("button", { name: "Select all currently shown" }).click();
    await page.getByText(/25 ready videos selected. Choose up to 20/).waitFor(); assert.equal(await generate(page).isDisabled(), true);
    await page.getByRole("button", { name: "Load more videos" }).click(); assert.equal(await select(page, 1).isChecked(), true);
    for (const n of [21, 22, 23, 24, 25]) await select(page, n).uncheck();
    await generate(page).click(); await generated(page); assert.equal(calls.find((call) => call.path.endsWith("/recommendations")).body.video_ids.length, 20);
  });
});
test("multi-asset ads count towards the 20-video limit", async () => {
  await withApp({ items: [video(30, { content_type: "ad", account_platform: "meta_ads", assets: Array.from({ length: 21 }, (_, i) => video(i + 1)) })] }, async (page) => {
    await select(page, 30).check(); await page.getByText(/21 ready videos selected/).waitFor(); assert.equal(await generate(page).isDisabled(), true);
  });
});
test("job result pagination and partial failure preserve successful content", async () => {
  await withApp({ route: async (route, url) => {
    if (!url.pathname.startsWith("/api/meta/jobs/")) return false;
    await route.fulfill({ json: job(jobId, { state: "partial_failure", counts: { completed: 4, failed: 1 }, next_cursor: url.searchParams.has("after") ? null : uuid(9999) }) }); return true;
  } }, async (page, calls) => {
    await loaded(page); await page.getByText(/Some content couldn’t be updated/).waitFor(); await select(page, 1).check(); assert.equal(await generate(page).isEnabled(), true);
    assert.equal(calls.some((call) => call.path.startsWith("/api/meta/jobs/") && call.url.searchParams.has("after")), true);
  });
});
for (const response of ["New video idea: A fresh idea\nScript: A usable script", "**New video idea**\nA fresh idea\n**Script**\nA usable script", "1. New video idea\nA fresh idea\n2. Script\nA usable script"]) {
  test(`text result sections: ${response.slice(0, 24)}`, async () => {
    await withApp({ response }, async (page) => { await loaded(page); await select(page, 1).check(); await generate(page).click(); await generated(page); assert.equal(await page.locator(".concept").innerText(), "A fresh idea"); assert.equal(await page.locator(".script").innerText(), "A usable script"); });
  });
}
test("unstructured response is preserved as safe text without internal references", async () => {
  await withApp({ response: `An exploratory idea for ${uuid(1)}. <script>bad()</script>` }, async (page) => {
    await loaded(page); await select(page, 1).check(); await generate(page).click(); await generated(page);
    assert.match(await page.locator(".script").innerText(), /Business video 1.*<script>/); assert.equal(await page.locator(".idea-result script").count(), 0); assert.doesNotMatch(await page.locator("main").innerText(), /00000000|private-model/);
  });
});
for (const [status, message] of [[413, "too much material"], [503, "couldn’t generate your idea"], [404, "no longer available"]]) {
  test(`recommendation ${status} preserves previous result`, async () => {
    let fail = false;
    await withApp({ route: async (route, url) => {
      if (!fail || url.pathname !== "/api/meta/recommendations") return false;
      await route.fulfill({ status, json: { detail: "private Graph API error" } }); return true;
    } }, async (page) => {
      await loaded(page); await select(page, 1).check(); await generate(page).click(); await generated(page); fail = true;
      await generate(page).click(); await page.getByText(new RegExp(message)).waitFor(); assert.equal(await page.locator(".idea-result").isVisible(), true); assert.equal(await select(page, 1).isChecked(), true);
    });
  });
}
test("409 queues outdated analysis rather than retrying recommendations automatically", async () => {
  const item = video(1);
  await withApp({ items: [item], route: async (route, url) => {
    if (url.pathname === "/api/meta/recommendations") { await route.fulfill({ status: 409, json: { detail: { message: "outdated", video_ids: [item.id] } } }); return true; }
    if (url.pathname === "/api/meta/library/analyze") { item.analysis_version = 2; await route.fulfill({ status: 202, json: { job_id: uuid(9001) } }); return true; }
    return false;
  } }, async (page, calls) => {
    await loaded(page); await select(page, 1).check(); await generate(page).click(); await page.getByText(/need to be prepared again/).waitFor();
    await page.waitForFunction(() => ![...document.querySelectorAll("button")].find((button) => button.textContent === "Generate a new video idea").disabled);
    assert.deepEqual(calls.find((call) => call.path === "/api/meta/library/analyze").body, { item_ids: [item.id] });
    assert.equal(calls.filter((call) => call.path === "/api/meta/recommendations").length, 1);
  });
});
test("expired connection retains successful content and reconnects", async () => {
  let expired = false;
  await withApp({ route: async (route, url) => {
    if (!expired || url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ status: 401, json: {} }); return true;
  } }, async (page) => {
    await loaded(page); await select(page, 1).check(); expired = true; await page.getByRole("button", { name: "Sync content", exact: true }).click();
    await page.getByText(/Your Meta connection has expired. Reconnect to continue/).waitFor(); assert.equal(await select(page, 1).isVisible(), true); assert.equal(await generate(page).isDisabled(), true);
    expired = false; await connect(page); await loaded(page);
  });
});
test("blocked job asks for reconnection and stops generation", async () => {
  await withApp({ route: async (route, url) => {
    if (!url.pathname.startsWith("/api/meta/jobs/")) return false;
    await route.fulfill({ json: job(jobId, { state: "blocked" }) }); return true;
  } }, async (page) => { await page.getByText(/Your Meta connection has expired. Reconnect to continue/).waitFor(); assert.equal(await generate(page).isDisabled(), true); });
});
for (const status of [403, 503]) {
  test(`library ${status} is not presented as an empty account`, async () => {
    await withApp({ route: async (route, url) => {
      if (url.pathname !== "/api/meta/library") return false;
      await route.fulfill({ status, json: { detail: "database Graph API private" } }); return true;
    } }, async (page) => { await page.getByRole("alert").waitFor(); assert.equal(await page.getByRole("heading", { name: "Your videos will appear here" }).count(), 0); assert.doesNotMatch(await page.locator("main").innerText(), /Graph|API|database/); });
  });
}
test("empty content library can sync without choosing an account", async () => {
  await withApp({ items: [] }, async (page, calls) => { await page.getByRole("heading", { name: "Your videos will appear here" }).waitFor(); assert.equal(calls.some((call) => call.path === "/api/meta/sync"), true); assert.equal(await generate(page).isDisabled(), true); });
});
test("legacy mocked shape is rejected", async () => {
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ json: { items: [{ id: uuid(1), status: "ready", title: "obsolete" }], next_cursor: null } }); return true;
  } }, async (page) => { await page.getByText("We couldn’t read the latest update. Please try again.").waitFor(); assert.equal(await generate(page).isDisabled(), true); });
});
test("blocked and closed popups are recoverable", async () => {
  await withApp({ connected: false }, async (page) => {
    await page.getByText("Meta is not connected.").waitFor(); await page.evaluate(() => { window.savedOpen = window.open; window.open = () => null; });
    await page.getByRole("button", { name: "Connect Meta", exact: true }).click(); await page.getByText(/Allow popups/).waitFor();
    await page.evaluate(() => { window.open = window.savedOpen; }); const opened = page.waitForEvent("popup"); await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
    const popup = await opened; await popup.getByRole("link", { name: "Continue with Meta" }).waitFor(); await popup.close(); await page.getByText(/authorization was not completed/).waitFor();
  });
});
test("desktop, mobile and 320px preserve layout, keyboard selection and result focus", async () => {
  await withApp({}, async (page) => {
    await loaded(page); await select(page, 1).focus(); await page.keyboard.press("Space"); assert.equal(await select(page, 1).isChecked(), true);
    for (const width of [1280, 390, 320]) { await page.setViewportSize({ width, height: 900 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); await page.screenshot({ path: `/tmp/meta-integrated-library-${width}.png`, fullPage: true }); }
    assert.equal(await page.locator('input[type="file"], input[type="url"], input[type="password"], pre').count(), 0);
    await generate(page).click(); await generated(page); assert.equal(await page.locator("#idea-title").evaluate((element) => document.activeElement === element), true);
    for (const width of [320, 1280]) { await page.setViewportSize({ width, height: 900 }); await page.locator(".idea-result").screenshot({ path: `/tmp/meta-integrated-idea-${width}.png` }); }
  });
});

for (const failSecond of [false, true]) test(`large deferred selection uses 100-item preparation batches (partial failure: ${failSecond})`, async () => {
  const assets = Array.from({ length: 105 }, (_, i) => video(i + 10, { analysis_state: "deferred", video_id: null }));
  const ad = video(1, { content_type: "ad", assets });
  let batches = 0;
  await withApp({ items: [ad], route: async (route, url) => {
    if (url.pathname !== "/api/meta/library/analyze") return false;
    batches++;
    if (failSecond && batches === 2) { await route.fulfill({ status: 503, json: {} }); return true; }
    const ids = route.request().postDataJSON().item_ids;
    for (const asset of assets) if (ids.includes(asset.id)) { asset.analysis_state = "completed"; asset.video_id = asset.id; }
    await route.fulfill({ status: 202, json: { job_id: uuid(9100 + batches) } }); return true;
  } }, async (page, calls) => {
    await loaded(page); await select(page, 1).check();
    await page.getByText(failSecond ? "100 of 105 videos ready. Your idea will use the ready videos." : "105 ready videos selected. Choose up to 20 ready videos for one idea. An ad can contain more than one video.", { exact: !failSecond }).waitFor();
    assert.deepEqual(calls.filter((call) => call.path.endsWith("/analyze")).map((call) => call.body.item_ids.length), [100, 5]);
    if (failSecond) await page.getByText("Your video library is temporarily unavailable. Please try again later.").waitFor();
    assert.equal(await select(page, 1).isChecked(), true);
  });
});

test("recommendations identify library leaves rather than assuming storage IDs are equal", async () => {
  await withApp({ items: [video(1, { video_id: uuid(777) })] }, async (page, calls) => {
    await loaded(page); await select(page, 1).check(); await generate(page).click(); await generated(page);
    assert.deepEqual(calls.find((call) => call.path.endsWith("/recommendations")).body, { video_ids: [uuid(1)] });
  });
});
