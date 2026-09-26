import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import { test as nodeTest, before, after } from "node:test";
const test = (name, run) => nodeTest(name, { timeout: 25000 }, run);
import { chromium } from "playwright";
const origin = "http://127.0.0.1:5179";
let server, browser;
before(async () => {
  server = spawn("./node_modules/.bin/vite", ["--host", "127.0.0.1", "--port", "5179", "--strictPort"], { stdio: "inherit" });
  for (let attempt = 0; attempt < 70; attempt++) {
    try { if ((await fetch(origin)).ok) break; } catch { /* wait for Vite */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  browser = await chromium.launch({ headless: true });
});
after(async () => { await browser?.close(); server?.kill(); });
const fb = { platform: "facebook", account_id: "123", page_id: "123" };
const ig = { platform: "instagram", account_id: "234", page_id: "123" };
const ad = { platform: "meta_ads", account_id: "act_345" };
const list = (items, next_cursor = null) => ({ items, next_cursor });
const video = (id, overrides = {}) => ({ id, source: fb, title: `Business video ${id}`, platform: "facebook", content_type: "facebook_reel", distribution: "organic", status: "ready", thumbnail_url: null, published_at: "2026-09-20T12:00:00Z", metrics: { views: 120, likes: 12, comments: null, shares: 0 }, ...overrides });
const snapshot = (items, overrides = {}) => ({ items, next_cursor: null, sync_state: "idle", source_errors: [], summary: { total: items.length, ...Object.fromEntries(["ready", "new", "analyzing", "unavailable", "failed"].map((state) => [state, items.filter((item) => item.status === state).length])) }, ...overrides });
const sameSource = (a, b) => a.platform === b.platform && a.account_id === b.account_id && a.page_id === b.page_id;
async function withApp(options, run) {
  const context = await browser.newContext();
  const calls = [];
  let connected = options.connected ?? true;
  await context.route("https://image.test/**", (route) => route.abort());
  await context.route("https://meta-provider.test/authorize", (route) => route.fulfill({ contentType: "text/html", body: `<a href="${origin}/api/meta/callback?code=mock&state=mock">Continue with Meta</a>` }));
  await context.route("**/api/**", async (route) => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    calls.push({ path, method: request.method(), body: request.postDataJSON(), url, headers: request.headers() });
    if (options.route && await options.route(route, url, calls)) return;
    if (path === "/api/meta/test") return route.fulfill({ status: connected ? 200 : 401, json: { connected } });
    if (path === "/api/meta/connect") return route.fulfill({ contentType: "text/html", body: '<script>location.href="https://meta-provider.test/authorize"</script>' });
    if (path === "/api/meta/callback") { connected = true; return route.fulfill({ json: { connected: true } }); }
    if (path === "/api/meta/discovery/pages") return route.fulfill({ json: list(options.pages ?? [{ id: "123", name: "Our business" }]) });
    if (/\/instagram-accounts$/.test(path)) return route.fulfill({ json: list(options.instagram ?? [{ id: "234", name: "Our Instagram" }]) });
    if (path === "/api/meta/discovery/ad-accounts") return route.fulfill({ json: list(options.ads ?? [{ id: "act_345", name: "Our advertising" }]) });
    if (path === "/api/meta/library") {
      const sources = JSON.parse(url.searchParams.get("sources"));
      const items = (options.items ?? [video("one"), video("two")]).filter((item) => sources.some((source) => sameSource(source, item.source)));
      return route.fulfill({ json: snapshot(items) });
    }
    if (path === "/api/meta/library/sync") return route.fulfill({ json: { accepted: true } });
    if (path === "/api/meta/library/recommendations") return route.fulfill({ json: { concept: "Show the story behind your service.", script: "Start with a customer question.\nShow your process.\nInvite viewers to visit.", used_item_ids: request.postDataJSON().item_ids, skipped_items: [] } });
    return route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
  const page = await context.newPage(), pageErrors = [];
  page.setDefaultTimeout(8000);
  page.on("pageerror", (error) => pageErrors.push(error.message));
  try { await page.goto(origin); await run(page, calls, context); assert.deepEqual(pageErrors, []); }
  finally { await context.close(); }
}
const select = (page, id) => page.getByRole("checkbox", { name: `Select Business video ${id}`, exact: true });
const generate = (page) => page.getByRole("button", { name: "Generate a new video idea", exact: true });
const loaded = (page) => select(page, "one").waitFor();
async function connect(page) {
  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
  const popup = await popupPromise;
  await popup.getByRole("link", { name: "Continue with Meta" }).click();
  await page.getByText("Meta connected successfully.").waitFor();
}

test("Meta popup verifies session, auto-selects sole accounts and loads library", async () => {
  await withApp({ connected: false }, async (page, calls) => {
    await page.getByText("Meta is not connected.").waitFor(); await connect(page); await loaded(page);
    for (const name of ["Our business", "Our Instagram", "Our advertising"]) assert.equal(await page.getByRole("checkbox", { name, exact: true }).isChecked(), true);
    assert.equal(calls.filter((call) => call.path === "/api/meta/test").length >= 2, true);
    assert.equal(calls.some((call) => call.path === "/api/meta/library/sync"), true);
  });
});
test("one ready selection generates concept and script without upload or credentials", async () => {
  await withApp({}, async (page, calls) => {
    await loaded(page); assert.equal(await generate(page).isDisabled(), true);
    await select(page, "one").check(); assert.equal(await generate(page).isEnabled(), true);
    await generate(page).click(); await page.getByRole("heading", { name: "New video idea", exact: true }).waitFor();
    assert.match(await page.locator(".idea-result").innerText(), /Based on 1 selected video/);
    assert.match(await page.locator(".script").innerText(), /Show your process/);
    const request = calls.find((call) => call.path.endsWith("/recommendations"));
    assert.deepEqual(request.body, { item_ids: ["one"] }); assert.equal(request.headers["x-openai-api-key"], undefined);
    assert.equal(calls.some((call) => call.path === "/api/videos"), false);
  });
});
test("multiple selections, individual deselect and clear selection", async () => {
  await withApp({}, async (page) => {
    await loaded(page); await select(page, "one").check(); await select(page, "two").check();
    await page.getByText("2 selected", { exact: true }).waitFor(); await select(page, "one").uncheck();
    await page.getByText("1 selected", { exact: true }).waitFor(); await page.getByRole("button", { name: "Clear selection" }).click();
    assert.equal(await select(page, "two").isChecked(), false); assert.equal(await generate(page).isDisabled(), true);
  });
});
test("multiple Pages require a choice and source changes clear selection", async () => {
  await withApp({ pages: [{ id: "123", name: "First shop" }, { id: "456", name: "Second shop" }], instagram: [], ads: [] }, async (page) => {
    const first = page.getByRole("checkbox", { name: "First shop" }); await first.waitFor(); assert.equal(await first.isChecked(), false);
    assert.equal(await page.getByRole("heading", { name: "Your video library" }).count(), 0);
    await first.check(); await loaded(page); await select(page, "one").check(); await page.getByRole("checkbox", { name: "Second shop" }).check();
    await loaded(page); assert.equal(await select(page, "one").isChecked(), false);
  });
});
test("account pagination completes before deciding auto-selection", async () => {
  await withApp({ instagram: [], ads: [], route: async (route, url) => {
    if (url.pathname !== "/api/meta/discovery/pages") return false;
    await route.fulfill({ json: url.searchParams.has("after") ? list([{ id: "456", name: "Second shop" }]) : list([{ id: "123", name: "First shop" }], "next") }); return true;
  } }, async (page, calls) => {
    await page.getByRole("checkbox", { name: "Second shop" }).waitFor(); assert.equal(await page.getByRole("checkbox", { name: "First shop" }).isChecked(), false);
    assert.equal(calls.some((call) => call.path === "/api/meta/library"), false);
  });
});
test("mixed Instagram, Facebook and paid ads generate one combined idea", async () => {
  await withApp({ items: [video("one"), video("two", { content_type: "facebook_video" }), video("three", { source: ig, platform: "instagram", content_type: "instagram_reel" }), video("four", { source: ad, platform: "meta_ads", content_type: "meta_video_ad", distribution: "paid" })] }, async (page, calls) => {
    await loaded(page);
    for (const label of ["Facebook Reel", "Facebook video", "Instagram Reel", "Meta video ad", "Paid ad"]) await page.getByText(label, { exact: true }).waitFor();
    await page.getByRole("button", { name: "Select all currently shown" }).click(); await generate(page).click(); await page.getByText("Based on 4 selected videos.").waitFor();
    assert.deepEqual(calls.filter((call) => call.path.endsWith("/recommendations")).map((call) => call.body), [{ item_ids: ["one", "two", "three", "four"] }]);
  });
});
test("250 videos across pages stay selected and generate a single batch", async () => {
  const items = Array.from({ length: 250 }, (_, index) => video(`batch-${index}`));
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    const second = url.searchParams.get("after") === "page-two";
    await route.fulfill({ json: snapshot(items.slice(second ? 125 : 0, second ? 250 : 125), { next_cursor: second ? null : "page-two", summary: snapshot(items).summary }) }); return true;
  } }, async (page, calls) => {
    await select(page, "batch-0").waitFor(); await page.getByRole("button", { name: "Select all currently shown" }).click();
    await page.getByRole("button", { name: "Load more videos" }).click(); await select(page, "batch-249").waitFor(); assert.equal(await select(page, "batch-0").isChecked(), true);
    await page.getByRole("button", { name: "Select all currently shown" }).click(); await page.getByText("250 selected", { exact: true }).waitFor();
    await generate(page).click(); await page.getByText("Based on 250 selected videos.").waitFor();
    assert.equal(await page.locator("#idea-title").evaluate((heading) => document.activeElement === heading && heading.getBoundingClientRect().top >= 0 && heading.getBoundingClientRect().bottom <= innerHeight), true);
    const requests = calls.filter((call) => call.path.endsWith("/recommendations")); assert.equal(requests.length, 1); assert.equal(new Set(requests[0].body.item_ids).size, 250);
  });
});
test("new content becomes analyzing then ready without losing selection", async () => {
  let state = "new";
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ json: snapshot([video("one", { status: state })]) }); return true;
  } }, async (page) => {
    await loaded(page); await select(page, "one").check(); assert.equal(await generate(page).isDisabled(), true);
    await page.getByText(/1 selected video is still processing/).waitFor(); state = "analyzing";
    await page.getByText("Analyzing", { exact: true }).waitFor({ timeout: 10000 }); state = "ready";
    await page.getByText("Ready", { exact: true }).waitFor({ timeout: 10000 });
    assert.equal(await select(page, "one").isChecked(), true); assert.equal(await generate(page).isEnabled(), true);
  });
});
test("mixed readiness sends only ready content and explains processing", async () => {
  await withApp({ items: [video("one"), video("two", { status: "analyzing" })] }, async (page, calls) => {
    await loaded(page); await page.getByRole("button", { name: "Select all currently shown" }).click(); await page.getByText(/Your idea will use the 1 ready video/).waitFor();
    await generate(page).click(); await page.getByText("Based on 1 selected video.").waitFor();
    assert.deepEqual(calls.find((call) => call.path.endsWith("/recommendations")).body.item_ids, ["one"]);
  });
});
test("saved ready videos are usable while sync is pending", async () => {
  let release; const barrier = new Promise((resolve) => { release = resolve; });
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library/sync") return false;
    await barrier; await route.fulfill({ json: { accepted: true } }); return true;
  } }, async (page) => {
    try { await loaded(page); await select(page, "one").check(); assert.equal(await generate(page).isEnabled(), true); } finally { release(); }
  });
});
test("failed and unavailable media cannot be selected; good videos remain", async () => {
  await withApp({ items: [video("one"), video("two", { status: "unavailable" }), video("three", { status: "failed" })] }, async (page) => {
    await loaded(page); assert.equal(await select(page, "two").isDisabled(), true); assert.equal(await select(page, "three").isDisabled(), true);
    await page.getByRole("button", { name: "Select all currently shown" }).click(); await page.getByText("1 selected", { exact: true }).waitFor(); assert.equal(await generate(page).isEnabled(), true);
  });
});
test("partial source failure preserves good content and identifies affected account", async () => {
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ json: snapshot([video("one")], { source_errors: [{ source: ad, code: "permission_missing" }] }) }); return true;
  } }, async (page) => { await loaded(page); await page.getByText(/Our advertising: Reconnect Meta/).waitFor(); await select(page, "one").check(); assert.equal(await generate(page).isEnabled(), true); });
});
test("partial recommendation success renders concept and explains skipped items", async () => {
  await withApp({ route: async (route, url) => {
    if (!url.pathname.endsWith("/recommendations")) return false;
    await route.fulfill({ json: { concept: "A fresh idea", script: "A usable script", used_item_ids: ["one"], skipped_items: [{ id: "two", code: "unavailable" }] } }); return true;
  } }, async (page) => {
    await loaded(page); await page.getByRole("button", { name: "Select all currently shown" }).click(); await generate(page).click();
    await page.getByText("A fresh idea", { exact: true }).waitFor(); await page.getByText(/1 selected video couldn’t be used/).waitFor(); assert.equal(await select(page, "one").isVisible(), true);
  });
});
test("generation error preserves previous result and selection and hides raw errors", async () => {
  let fail = false;
  await withApp({ route: async (route, url) => {
    if (!fail || !url.pathname.endsWith("/recommendations")) return false;
    await route.fulfill({ status: 503, json: { detail: "OpenAI API key missing uuid-private-value" } }); return true;
  } }, async (page) => {
    await loaded(page); await select(page, "one").check(); await generate(page).click(); await page.getByRole("heading", { name: "New video idea", exact: true }).waitFor(); fail = true;
    await generate(page).click(); await page.getByRole("alert").getByText(/We couldn’t generate your idea/).waitFor();
    assert.equal(await page.locator(".idea-result").isVisible(), true); assert.equal(await select(page, "one").isChecked(), true); assert.doesNotMatch(await page.locator("main").innerText(), /OpenAI|uuid-private-value|API/);
  });
});
test("expired connection preserves content and results and allows reconnect", async () => {
  let expired = false;
  await withApp({ route: async (route, url) => {
    if (!expired || url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ status: 401, json: {} }); return true;
  } }, async (page) => {
    await loaded(page); await select(page, "one").check(); await generate(page).click(); await page.getByRole("heading", { name: "New video idea", exact: true }).waitFor(); expired = true;
    await page.getByRole("button", { name: "Sync content", exact: true }).click(); await page.getByText(/Your Meta connection has expired. Reconnect to continue/).waitFor();
    assert.equal(await select(page, "one").isVisible(), true); assert.equal(await generate(page).isDisabled(), true); assert.equal(await page.locator(".idea-result").isVisible(), true);
    expired = false; await connect(page);
    await page.waitForFunction(() => ![...document.querySelectorAll("button")].find((button) => button.textContent === "Generate a new video idea").disabled);
  });
});
for (const [status, message] of [[403, "Some content isn’t shared with us"], [404, "Your video library isn’t available yet"], [501, "Your video library isn’t available yet"], [502, "We couldn’t update your library"]]) {
  test(`library ${status} has a friendly error, not a false empty library`, async () => {
    await withApp({ route: async (route, url) => {
      if (url.pathname !== "/api/meta/library") return false;
      await route.fulfill({ status, json: { detail: "Graph API private UUID" } }); return true;
    } }, async (page) => {
      await page.getByText(new RegExp(message)).waitFor(); assert.equal(await page.getByText("Your videos will appear here", { exact: true }).count(), 0); assert.doesNotMatch(await page.locator("main").innerText(), /Graph|UUID|API/);
    });
  });
}
test("empty library and no suitable content have distinct states", async () => {
  await withApp({ items: [] }, async (page) => { await page.getByRole("heading", { name: "Your videos will appear here" }).waitFor(); assert.equal(await generate(page).isDisabled(), true); });
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ json: snapshot([], { summary: { total: 2, ready: 0, new: 0, analyzing: 0, unavailable: 2, failed: 0 } }) }); return true;
  } }, async (page) => { await page.getByRole("heading", { name: "No suitable videos available" }).waitFor(); });
});
test("disconnected state has no manual inputs or technical content", async () => {
  await withApp({ connected: false }, async (page, calls) => {
    await page.getByRole("button", { name: "Connect Meta", exact: true }).waitFor(); assert.equal(await page.locator('input[type="file"], input[type="url"], input[type="password"], pre').count(), 0);
    assert.equal(calls.some((call) => call.path === "/api/meta/library"), false); assert.doesNotMatch(await page.locator("main").innerText(), /Graph|API|UUID|Analyze video|Video file/);
  });
});
test("blocked and closed Meta popups allow retry", async () => {
  await withApp({ connected: false }, async (page) => {
    await page.getByText("Meta is not connected.").waitFor(); await page.evaluate(() => { window.savedOpen = window.open; window.open = () => null; });
    await page.getByRole("button", { name: "Connect Meta", exact: true }).click(); await page.getByText(/Allow popups/).waitFor();
    await page.evaluate(() => { window.open = window.savedOpen; }); const popupPromise = page.waitForEvent("popup"); await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
    const popup = await popupPromise;
    await popup.getByRole("link", { name: "Continue with Meta" }).waitFor();
    await popup.close(); await page.getByText(/authorization was not completed/).waitFor(); assert.equal(await page.getByRole("button", { name: "Connect Meta", exact: true }).isEnabled(), true);
  });
});
test("connection network failure is friendly", async () => {
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/test") return false;
    await route.abort(); return true;
  } }, async (page) => { await page.getByText("Could not check the Meta connection. Try connecting again.").waitFor(); });
});
test("malformed response cannot enable generation", async () => {
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ json: { items: [{ id: "private", status: "ready" }] } }); return true;
  } }, async (page) => { await page.getByText("We couldn’t read the latest update. Please try again.").waitFor(); assert.equal(await generate(page).isDisabled(), true); });
});
test("desktop and narrow phones have readable cards, image fallbacks and keyboard selection", async () => {
  await withApp({ items: [video("one", { thumbnail_url: "https://image.test/missing.jpg" }), video("two", { source: ad, platform: "meta_ads", content_type: "meta_video_ad", distribution: "paid" })] }, async (page) => {
    await loaded(page); await select(page, "one").focus(); await page.keyboard.press("Space"); assert.equal(await select(page, "one").isChecked(), true);
    for (const width of [1280, 390, 320]) {
      await page.setViewportSize({ width, height: 900 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true); assert.equal(await generate(page).isVisible(), true);
      await page.screenshot({ path: `/tmp/meta-library-${width}.png`, fullPage: true });
    }
    assert.equal(await page.locator(".thumbnail-placeholder").count(), 2); assert.equal(await page.locator('input[type="file"], input[type="url"], input[type="password"], pre').count(), 0);
    assert.doesNotMatch(await page.locator("main").innerText(), /act_345|\b123\b|\b234\b|Graph|API|UUID/);
    await generate(page).click();
    await page.getByRole("heading", { name: "New video idea", exact: true }).waitFor();
    for (const width of [320, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.locator(".idea-result").screenshot({ path: `/tmp/meta-idea-${width}.png` });
    }
  });
});

test("multiple Instagram and ad accounts remain explicit named choices", async () => {
  await withApp({ pages: [{ id: "123", name: "First shop" }, { id: "456", name: "Second shop" }], ads: [{ id: "act_345", name: "Local advertising" }, { id: "act_678", name: "National advertising" }], route: async (route, url) => {
    if (!url.pathname.endsWith("/instagram-accounts")) return false;
    await route.fulfill({ json: list(url.pathname.includes("/123/") ? [{ id: "234", name: "First Instagram" }] : [{ id: "567", name: "Second Instagram" }]) }); return true;
  } }, async (page, calls) => {
    for (const name of ["First Instagram", "Second Instagram", "Local advertising", "National advertising"]) {
      const choice = page.getByRole("checkbox", { name, exact: true }); await choice.waitFor(); assert.equal(await choice.isChecked(), false); await choice.check();
    }
    await page.getByRole("heading", { name: "Your videos will appear here" }).waitFor();
    const last = calls.filter((call) => call.path === "/api/meta/library").at(-1);
    assert.equal(JSON.parse(last.url.searchParams.get("sources")).length, 4);
  });
});

test("partial account discovery failure still loads successful sources and retries", async () => {
  let fail = true;
  await withApp({ route: async (route, url) => {
    if (!fail || url.pathname !== "/api/meta/discovery/ad-accounts") return false;
    await route.fulfill({ status: 403, json: { detail: "Graph permission code" } }); return true;
  } }, async (page) => {
    await loaded(page); await page.getByText(/Some content isn’t shared with us/).waitFor();
    await select(page, "one").check(); assert.equal(await generate(page).isEnabled(), true);
    fail = false; await page.getByRole("button", { name: "Try accounts again" }).click();
    await page.getByRole("checkbox", { name: "Our advertising" }).waitFor(); assert.equal(await select(page, "one").isChecked(), true);
  });
});

test("failed sync keeps ready content and selection available", async () => {
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library/sync") return false;
    await route.fulfill({ status: 502, json: {} }); return true;
  } }, async (page) => {
    await loaded(page); await page.getByText(/We couldn’t update your library/).waitFor(); await select(page, "one").check();
    assert.equal(await generate(page).isEnabled(), true);
    await generate(page).click(); await page.getByRole("heading", { name: "New video idea", exact: true }).waitFor();
  });
});

test("polling updates the second loaded page and preserves its selection", async () => {
  let state = "new";
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    const second = url.searchParams.has("after");
    const all = [video("one"), video("two", { status: state })];
    await route.fulfill({ json: snapshot(second ? [all[1]] : [all[0]], { next_cursor: second ? null : "next-page", summary: snapshot(all).summary }) }); return true;
  } }, async (page) => {
    await loaded(page); await page.getByRole("button", { name: "Load more videos" }).click(); await select(page, "two").check();
    assert.equal(await generate(page).isDisabled(), true); state = "ready";
    await page.waitForFunction(() => ![...document.querySelectorAll("button")].find((button) => button.textContent === "Generate a new video idea").disabled, { timeout: 10000 });
    assert.equal(await select(page, "two").isChecked(), true);
  });
});

test("changing source scope cancels a stale library response", async () => {
  let release;
  const barrier = new Promise((resolve) => { release = resolve; });
  let delayed = false;
  await withApp({ pages: [{ id: "123", name: "First shop" }, { id: "456", name: "Second shop" }], instagram: [], ads: [], route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    const sources = JSON.parse(url.searchParams.get("sources"));
    if (sources.length === 1 && sources[0].account_id === "123") {
      delayed = true; await barrier;
      await route.fulfill({ json: snapshot([video("stale")]) }); return true;
    }
    return false;
  } }, async (page) => {
    await page.getByRole("checkbox", { name: "First shop" }).check();
    for (let retry = 0; retry < 160 && !delayed; retry++) await new Promise((resolve) => setTimeout(resolve, 25));
    assert.equal(delayed, true);
    await page.getByRole("checkbox", { name: "Second shop" }).check(); await loaded(page);
    release(); await page.getByRole("checkbox", { name: "First shop" }).uncheck();
    await page.getByRole("heading", { name: "Your videos will appear here" }).waitFor(); assert.equal(await select(page, "stale").count(), 0);
  });
});

for (const status of [403, 503]) {
  test(`Meta callback ${status} hides provider details and allows retry`, async () => {
    await withApp({ connected: false, route: async (route, url) => {
      if (url.pathname !== "/api/meta/callback") return false;
      await route.fulfill({ status, json: { detail: "Graph API private permission error" } }); return true;
    } }, async (page) => {
      const popupPromise = page.waitForEvent("popup"); await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
      await (await popupPromise).getByRole("link", { name: "Continue with Meta" }).click();
      await page.getByText(/We couldn’t connect Meta/).waitFor(); assert.equal(await page.getByRole("button", { name: "Connect Meta", exact: true }).isEnabled(), true);
      assert.doesNotMatch(await page.locator("main").innerText(), /Graph|API|private permission/);
    });
  });
}

test("malformed recommendation preserves the last successful result", async () => {
  let malformed = false;
  await withApp({ route: async (route, url) => {
    if (!malformed || !url.pathname.endsWith("/recommendations")) return false;
    await route.fulfill({ json: { concept: "Wrong result", script: "Wrong script", used_item_ids: ["unrequested-reference"], skipped_items: [] } }); return true;
  } }, async (page) => {
    await loaded(page); await select(page, "one").check(); await generate(page).click(); await page.getByRole("heading", { name: "New video idea", exact: true }).waitFor();
    malformed = true; await generate(page).click(); await page.getByText("We couldn’t read the latest update. Please try again.").waitFor();
    assert.match(await page.locator(".idea-result").innerText(), /Show the story behind your service/); assert.equal(await page.getByText("Wrong result", { exact: true }).count(), 0);
  });
});

test("source failures with no loaded items never claim the library is empty", async () => {
  await withApp({ route: async (route, url) => {
    if (url.pathname !== "/api/meta/library") return false;
    await route.fulfill({ json: snapshot([], { source_errors: [{ source: fb, code: "permission_missing" }] }) }); return true;
  } }, async (page) => {
    await page.getByRole("heading", { name: "Some content is unavailable" }).waitFor();
    assert.equal(await page.getByRole("heading", { name: "Your videos will appear here" }).count(), 0);
    assert.equal(await generate(page).isDisabled(), true);
  });
});
