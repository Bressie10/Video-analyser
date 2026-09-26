import { spawn } from "node:child_process";
import assert from "node:assert/strict";
import { test } from "node:test";
import { chromium } from "playwright";

const origin = "http://127.0.0.1:5179";
const server = spawn("./node_modules/.bin/vite", ["--host", "127.0.0.1", "--port", "5179", "--strictPort"], { stdio: "ignore" });

async function waitForServer() {
  for (let attempt = 0; attempt < 50; attempt++) {
    try { if ((await fetch(origin)).ok) return; } catch { /* still starting */ }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Vite did not start");
}

const saved = {
  video_id: "8db7e284-353b-4f3e-9bf0-44d78d888720",
  metadata: { duration_seconds: 12.3, video: { resolution: { width: 1080, height: 1920 }, fps: 30 } },
  audio: { text: "Hello world" },
  scenes: [{ scene_number: 1, start_seconds: 0, end_seconds: 12.3 }],
  on_screen_text: [{ text: "Watch this", appearance_timestamp_seconds: 1, disappearance_timestamp_seconds: 3 }],
  motion_events: [{ type: "camera_pan", start_seconds: 2, end_seconds: 4 }],
  performance_source: "tiktok",
  performance_metrics: { view_count: 120, like_count: 12, comment_count: null, share_count: 2 },
};

async function fillForm(page) {
  await page.locator("#video").setInputFiles({ name: "sample.mp4", mimeType: "video/mp4", buffer: Buffer.from("sample") });
  await page.locator("#tiktok-url").fill("https://www.tiktok.com/@creator/video/123456789");
  await page.locator("#api-key").fill("test-runtime-key");
  await page.getByRole("button", { name: "Analyze video" }).click();
}

test("browser completes upload, saved analysis, and recommendation flow", async () => {
  await waitForServer();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const calls = [];
    await page.route("**/api/videos", async (route) => {
      const request = route.request();
      calls.push("upload");
      assert.match(request.postData() ?? "", /sample\.mp4/);
      assert.match(request.postData() ?? "", /https:\/\/www\.tiktok\.com\/@creator\/video\/123456789/);
      assert.doesNotMatch(request.postData() ?? "", /test-runtime-key/);
      await route.fulfill({ status: 200, json: saved });
    });
    await page.route("**/api/videos/*/analysis", async (route) => {
      calls.push("stored analysis");
      await route.fulfill({ status: 200, json: saved });
    });
    await page.route("**/api/videos/*/recommendations", async (route) => {
      calls.push("recommendation");
      assert.equal(route.request().headers()["x-openai-api-key"], "test-runtime-key");
      await route.fulfill({ status: 200, json: { model: "gpt-6-sol", response: "New video idea: A fresh concept.\nScript: Hello there." } });
    });
    await page.goto(origin);
    await fillForm(page);
    await page.getByText("Analysis complete.").waitFor();
    assert.deepEqual(calls, ["upload", "stored analysis", "recommendation"]);
    assert.match(await page.locator("main").innerText(), /120[\s\S]*12[\s\S]*Unavailable[\s\S]*2/);
    assert.match(await page.locator("main").innerText(), /Hello world/);
    assert.match(await page.locator("main").innerText(), /camera pan/);
    assert.match(await page.locator("main").innerText(), /New video idea:[\s\S]*Script:/);
    await page.getByText("Full analysis data").click();
    assert.match(await page.locator("pre").innerText(), /"comment_count": null/);
    assert.equal(await page.locator("#api-key").getAttribute("type"), "password");
  } finally { await browser.close(); }
});

test("recommendation error keeps saved video analysis visible", async () => {
  await waitForServer();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.route("**/api/videos", (route) => route.fulfill({ status: 200, json: saved }));
    await page.route("**/api/videos/*/analysis", (route) => route.fulfill({ status: 200, json: saved }));
    await page.route("**/api/videos/*/recommendations", (route) => route.fulfill({ status: 502, json: { detail: "OpenAI request failed." } }));
    await page.goto(origin);
    await fillForm(page);
    await page.getByRole("alert").getByText("OpenAI request failed.").waitFor();
    assert.equal(await page.getByRole("heading", { name: "Video analysis" }).count(), 1);
  } finally { await browser.close(); }
});

test("browser displays backend error and stops after failed upload", async () => {
  await waitForServer();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.route("**/api/videos", (route) => route.fulfill({ status: 401, json: { detail: "TikTok account is not connected." } }));
    await page.goto(origin);
    await fillForm(page);
    await page.getByRole("alert").getByText("TikTok account is not connected.").waitFor();
    assert.equal(await page.getByRole("heading", { name: "Video analysis" }).count(), 0);
  } finally { await browser.close(); }
});

test.after(() => server.kill());

async function metaPage(run, initial = { status: 401, json: {} }) {
  await waitForServer();
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext();
    await context.route("**/api/meta/test", (route) => route.fulfill(initial));
    await mockDiscovery(context);
    const page = await context.newPage();
    await page.goto(origin);
    await run(page, context);
  } finally { await browser.close(); }
}

test("Meta existing session and mobile layout", async () => {
  await metaPage(async (page) => {
    await page.getByText("Meta connected successfully.").waitFor();
    for (const width of [1280, 320]) {
      await page.setViewportSize({ width, height: 900 });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.getByRole("button", { name: "Reconnect Meta" }).isVisible(), true);
      await page.screenshot({ path: `/tmp/meta-connection-${width}.png`, fullPage: true });
    }
  }, { status: 200, json: { connected: true } });
});

test("Meta popup follows OAuth redirect and verifies session", async () => {
  await metaPage(async (page, context) => {
    await page.getByText("Meta is not connected.").waitFor();
    const paths = [];
    context.on("request", (request) => { if (request.url().includes("/api/")) paths.push(new URL(request.url()).pathname); });
    await context.route("**/api/meta/connect", (route) => route.fulfill({ contentType: "text/html", body: '<script>location.href="https://meta-provider.test/authorize"</script>' }));
    await context.route("https://meta-provider.test/authorize", (route) => route.fulfill({ contentType: "text/html", body: '<a href="http://127.0.0.1:5179/api/meta/callback?code=mock&state=mock">Authorize</a>' }));
    await context.route("**/api/meta/callback?*", async (route) => {
      await context.route("**/api/meta/test", (check) => check.fulfill({ json: { connected: true } }));
      await route.fulfill({ json: { connected: true } });
    });
    const popupPromise = page.waitForEvent("popup");
    await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
    const popup = await popupPromise;
    await page.getByText("Connecting to Meta… Complete authorization in the popup window.").waitFor();
    assert.equal(await page.getByRole("button", { name: "Connecting…", exact: true }).isDisabled(), true);
    await popup.getByRole("link", { name: "Authorize" }).click();
    await page.getByText("Meta connected successfully.").waitFor();
    assert.equal(popup.isClosed(), true);
    assert.deepEqual(paths, ["/api/meta/connect", "/api/meta/callback", "/api/meta/test"]);
    await context.route("**/api/videos", (route) => route.fulfill({ json: contentOnly }));
    await context.route("**/api/videos/*/analysis", (route) => route.fulfill({ json: contentOnly }));
    await context.route("**/api/meta/instagram/reels/*/metrics", (route) => route.fulfill({ json: {
      performance_source: "instagram", performance_metrics: saved.performance_metrics,
    } }));
    await context.route("**/api/videos/*/recommendations", (route) => route.fulfill({ json: { response: "Connected and analyzed" } }));
    await fillInstagram(page);
    await page.getByRole("button", { name: "Analyze video", exact: true }).click();
    await page.getByText("Analysis complete.").waitFor();
    await page.getByText("Connected and analyzed").waitFor();
  });
});

for (const [name, path, status, detail] of [
  ["denied authorization", "/api/meta/callback?error=access_denied", 400, "Meta authorization was not completed."],
  ["invalid state", "/api/meta/callback?state=bad", 400, "Invalid Meta authorization state."],
  ["provider failure", "/api/meta/callback?code=mock", 502, "Meta authorization failed. Connect again."],
  ["missing configuration", "/api/meta/connect", 503, "Meta is not configured correctly."],
]) {
  test(`Meta displays ${name} and allows retry`, async () => {
    await metaPage(async (page, context) => {
      await context.route("**/api/meta/connect", (route) => path === "/api/meta/connect"
        ? route.fulfill({ status, json: { detail } })
        : route.fulfill({ contentType: "text/html", body: `<script>location.href=${JSON.stringify(path)}</script>` }));
      await context.route("**/api/meta/callback?*", (route) => route.fulfill({ status, json: { detail } }));
      await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
      await page.getByRole("alert").getByText(detail, { exact: true }).waitFor();
      assert.equal(await page.getByRole("button", { name: "Connect Meta", exact: true }).isEnabled(), true);
    });
  });
}

test("Meta handles blocked and closed popups", async () => {
  await metaPage(async (page, context) => {
    await page.evaluate(() => { window.originalOpen = window.open; window.open = () => null; });
    await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
    await page.getByText("Allow popups for this site, then select Connect Meta again.").waitFor();
    await page.evaluate(() => { window.open = window.originalOpen; });
    await context.route("**/api/meta/connect", (route) => route.fulfill({ contentType: "text/html", body: "Authorizing" }));
    const popupPromise = page.waitForEvent("popup");
    await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
    await (await popupPromise).close();
    await page.getByText("Meta authorization was not completed. Select Connect Meta to try again.").waitFor();
  });
});

test("Meta handles network errors and initial loading", async () => {
  await metaPage(async (page, context) => {
    await context.route("**/api/meta/test", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.abort();
    });
    await page.reload();
    await page.getByText("Checking Meta connection…").waitFor();
    assert.equal(await page.getByRole("button", { name: "Connect Meta", exact: true }).isDisabled(), true);
    await page.getByText("Could not check the Meta connection. Try connecting again.").waitFor();
    assert.equal(await page.getByRole("button", { name: "Connect Meta", exact: true }).isEnabled(), true);
  });
});

async function fillInstagram(page) {
  await page.locator("#platform").selectOption("instagram");
  await page.locator("#video").setInputFiles({ name: "reel.mp4", mimeType: "video/mp4", buffer: Buffer.from("sample") });
  await page.getByRole("button", { name: /Fresh bread/ }).click();
  await page.locator("#api-key").fill("test-runtime-key");
}

const contentOnly = { ...saved, performance_source: undefined, performance_metrics: undefined };

test("Instagram uploads without TikTok fields, attaches metrics, then recommends", async () => {
  await metaPage(async (page, context) => {
    const calls = [];
    await page.locator("#tiktok-url").fill("https://www.tiktok.com/@creator/video/123456789");
    await context.route("**/api/videos", async (route) => {
      calls.push("upload");
      assert.match(route.request().postData(), /reel\.mp4/);
      assert.doesNotMatch(route.request().postData(), /tiktok_url|123456789|17895695668004550|test-runtime-key/);
      await route.fulfill({ json: contentOnly });
    });
    await context.route("**/api/videos/*/analysis", async (route) => {
      calls.push("analysis"); await route.fulfill({ json: contentOnly });
    });
    await context.route("**/api/meta/instagram/reels/*/metrics", async (route) => {
      calls.push("metrics");
      assert.equal(route.request().method(), "POST");
      assert.equal(new URL(route.request().url()).pathname, "/api/meta/instagram/reels/17895695668004550/metrics");
      assert.deepEqual(route.request().postDataJSON(), { video_id: saved.video_id });
      assert.equal(route.request().headers()["x-openai-api-key"], undefined);
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({ json: { video_id: saved.video_id, performance_source: "instagram", performance_metrics: saved.performance_metrics } });
    });
    await context.route("**/api/videos/*/recommendations", async (route) => {
      calls.push("recommendation");
      assert.equal(route.request().headers()["x-openai-api-key"], "test-runtime-key");
      await route.fulfill({ json: { model: "test", response: "Reel idea and script" } });
    });
    await fillInstagram(page);
    await page.getByRole("button", { name: "Analyze video", exact: true }).click();
    await page.getByText("Retrieving Instagram Reel metrics…").waitFor();
    assert.equal(await page.locator("#platform").isDisabled(), true);
    await page.getByText("Analysis complete.").waitFor();
    await page.getByText("Reel idea and script").waitFor();
    assert.deepEqual(calls, ["upload", "analysis", "metrics", "recommendation"]);
    assert.match(await page.locator(".stats").innerText(), /120/);
    await page.getByText("Meta connected successfully.").waitFor();
  }, { status: 200, json: { connected: true } });
});

test("Disconnected users cannot submit Meta content or enter IDs", async () => {
  await metaPage(async (page) => {
    await page.locator("#platform").selectOption("instagram");
    await page.getByText("Connect Meta above to browse your Pages, accounts, and content.").waitFor();
    assert.equal(await page.locator("#meta-identifier").count(), 0);
    assert.equal(await page.getByRole("button", { name: "Analyze video", exact: true }).isDisabled(), true);
  });
});

for (const status of [401, 422, 502]) {
  test(`Instagram metrics ${status} preserves analysis and stops recommendations`, async () => {
    await metaPage(async (page, context) => {
      let recommendations = 0;
      await context.route("**/api/videos", (route) => route.fulfill({ json: contentOnly }));
      await context.route("**/api/videos/*/analysis", (route) => route.fulfill({ json: contentOnly }));
      await context.route("**/api/meta/instagram/reels/*/metrics", (route) => route.fulfill({ status, json: { detail: "Instagram metrics unavailable for this account." } }));
      await context.route("**/api/videos/*/recommendations", (route) => { recommendations++; return route.abort(); });
      await fillInstagram(page);
      await page.getByRole("button", { name: "Analyze video", exact: true }).click();
      await page.getByRole("alert").getByText("Instagram metrics unavailable for this account.").waitFor();
      assert.equal(await page.getByRole("heading", { name: "Video analysis", exact: true }).isVisible(), true);
      assert.equal(await page.locator("#platform").isEnabled(), true);
      assert.equal(recommendations, 0);
    }, { status: 200, json: { connected: true } });
  });
}

test("Meta content stays readable on desktop and narrow phones without exposed IDs", async () => {
  await metaPage(async (page) => {
    for (const platform of ["instagram", "facebook", "meta_ads"]) {
      await page.locator("#platform").selectOption(platform);
      await page.getByRole("button", { name: /Fresh bread/ }).waitFor();
      for (const width of [1280, 320]) {
        await page.setViewportSize({ width, height: 1000 });
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
        await page.screenshot({ path: `/tmp/meta-content-${platform}-${width}.png`, fullPage: true });
      }
      assert.doesNotMatch(await page.locator("main").innerText(), /17895695668004550|act_345|Graph media ID|Page ID/);
    }
  }, { status: 200, json: { connected: true } });
});

for (const kind of ["reels", "videos"]) {
  test(`Facebook ${kind} selects content and attaches metrics before recommending`, async () => {
    await metaPage(async (page, context) => {
      const calls = [];
      await context.route("**/api/videos", async (route) => {
        calls.push("upload");
        assert.doesNotMatch(route.request().postData(), /tiktok_url|test-runtime-key/);
        await route.fulfill({ json: contentOnly });
      });
      await context.route("**/api/videos/*/analysis", (route) => route.fulfill({ json: contentOnly }));
      await context.route("**/api/meta/facebook/*/*/metrics", async (route) => {
        calls.push("metrics");
        assert.equal(new URL(route.request().url()).pathname, `/api/meta/facebook/${kind}/456/metrics`);
        assert.deepEqual(route.request().postDataJSON(), { video_id: saved.video_id, page_id: "123" });
        await route.fulfill({ json: { performance_source: "facebook", performance_metrics: saved.performance_metrics } });
      });
      await context.route("**/api/videos/*/recommendations", async (route) => {
        calls.push("recommendation"); await route.fulfill({ json: { model: "test", response: "Facebook script" } });
      });
      await fillInstagram(page);
      await page.locator("#platform").selectOption("facebook");
      await page.locator("#facebook-kind").selectOption(kind);
      await page.getByRole("button", { name: /Fresh bread/ }).click();
      await page.getByRole("button", { name: "Analyze video", exact: true }).click();
      await page.getByText("Analysis complete.").waitFor();
      await page.getByText("Facebook script").waitFor();
      assert.deepEqual(calls, ["upload", "metrics", "recommendation"]);
    }, { status: 200, json: { connected: true } });
  });
}

async function mockDiscovery(context) {
  await context.route("**/api/meta/discovery/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    const items = path.endsWith("/pages") ? [{ id: "123", name: "Our bakery", type: "page" }]
      : path.endsWith("/instagram-accounts") ? [{ id: "234", name: "Bakery Instagram", type: "instagram" }]
      : path.endsWith("/ad-accounts") ? [{ id: "act_345", name: "Bakery advertising", type: "ad_account" }]
      : [{ id: path.endsWith("/media") ? "17895695668004550" : "456", name: "Fresh bread", type: "REELS", created_at: "2026-09-01T10:00:00Z" }];
    return route.fulfill({ json: { items, next_cursor: null } });
  });
}

test("Meta ad selection attaches metrics with chosen reporting dates", async () => {
  await metaPage(async (page, context) => {
    const calls = [];
    await context.route("**/api/videos", (route) => { calls.push("upload"); return route.fulfill({ json: contentOnly }); });
    await context.route("**/api/videos/*/analysis", (route) => route.fulfill({ json: contentOnly }));
    await context.route("**/api/meta/ads/456/metrics", (route) => {
      calls.push("metrics");
      assert.deepEqual(route.request().postDataJSON(), { video_id: saved.video_id, since: "2026-09-01", until: "2026-09-20" });
      return route.fulfill({ json: { performance_source: "meta_ads", performance_metrics: saved.performance_metrics } });
    });
    await context.route("**/api/videos/*/recommendations", (route) => { calls.push("recommendation"); return route.fulfill({ json: { response: "Ad script" } }); });
    await page.locator("#platform").selectOption("meta_ads");
    await page.getByRole("button", { name: /Fresh bread/ }).click();
    await page.locator("#ad-since").fill("2026-09-01");
    await page.locator("#ad-until").fill("2026-09-20");
    await page.locator("#video").setInputFiles({ name: "ad.mp4", mimeType: "video/mp4", buffer: Buffer.from("sample") });
    await page.locator("#api-key").fill("test-runtime-key");
    await page.getByRole("button", { name: "Analyze video", exact: true }).click();
    await page.getByText("Analysis complete.").waitFor();
    assert.deepEqual(calls, ["upload", "metrics", "recommendation"]);
  }, { status: 200, json: { connected: true } });
});

for (const status of [200, 403, 401, 502]) {
  test(`Discovery handles ${status} empty/error state`, async () => {
    await metaPage(async (page, context) => {
      await context.route("**/api/meta/discovery/pages", (route) => route.fulfill({ status,
        json: status === 200 ? { items: [], next_cursor: null } : { detail: "Reconnect Meta and allow access to your Page." } }));
      await page.locator("#platform").selectOption("instagram");
      await page.getByText(status === 200 ? /No facebook pages available/ : status === 401
        ? "Meta is not connected." : "Reconnect Meta and allow access to your Page.", { exact: status === 401 }).waitFor();
      assert.equal(await page.getByRole("button", { name: "Analyze video", exact: true }).isDisabled(), true);
      if (status === 403 || status === 502) {
        await mockDiscovery(context);
        await page.getByRole("button", { name: "Try again" }).click();
        await page.getByRole("button", { name: /Fresh bread/ }).waitFor();
      }
    }, { status: 200, json: { connected: true } });
  });
}

test("Pages paginate and changing Page clears selected content", async () => {
  await metaPage(async (page, context) => {
    await context.route("**/api/meta/discovery/pages*", async (route) => {
      const later = new URL(route.request().url()).searchParams.has("after");
      await route.fulfill({ json: { items: [{ id: later ? "999" : "123", name: later ? "Second bakery" : "Our bakery", type: "page" }], next_cursor: later ? null : "more" } });
    });
    await page.locator("#platform").selectOption("facebook");
    await page.getByRole("button", { name: "Our bakery", exact: true }).click();
    await page.getByRole("button", { name: /Fresh bread/ }).click();
    assert.equal(await page.getByRole("button", { name: "Analyze video", exact: true }).isEnabled(), true);
    await page.getByRole("button", { name: /Load more facebook pages/ }).click();
    await page.getByRole("button", { name: "Second bakery", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: "Analyze video", exact: true }).isDisabled(), true);
  }, { status: 200, json: { connected: true } });
});

test("Reconnecting clears selection and reloads assets after an expired session", async () => {
  await metaPage(async (page, context) => {
    await page.locator("#platform").selectOption("facebook");
    await page.getByRole("button", { name: /Fresh bread/ }).click();
    await context.route("**/api/meta/discovery/pages/123/facebook/videos", (route) => route.fulfill({ status: 401, json: {} }));
    await page.locator("#facebook-kind").selectOption("videos");
    await page.getByText("Meta is not connected.").waitFor();
    await context.route("**/api/meta/connect", (route) => route.fulfill({ json: { connected: true } }));
    await page.getByRole("button", { name: "Connect Meta", exact: true }).click();
    await page.getByText("Meta connected successfully.").waitFor();
    await page.getByRole("button", { name: /Fresh bread/ }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Analyze video", exact: true }).isDisabled(), true);
    await page.getByRole("button", { name: /Fresh bread/ }).click();
    assert.equal(await page.getByRole("button", { name: "Analyze video", exact: true }).isEnabled(), true);
  }, { status: 200, json: { connected: true } });
});

test("Content pagination, unsupported Instagram posts, and loading state", async () => {
  await metaPage(async (page, context) => {
    await context.route("**/api/meta/discovery/pages/123/instagram/234/media*", async (route) => {
      const later = new URL(route.request().url()).searchParams.has("after");
      await new Promise((resolve) => setTimeout(resolve, 300));
      await route.fulfill({ json: { items: later
        ? [{ id: "555", name: "Weekend Reel", type: "REELS", selectable: true }]
        : [{ id: "444", name: "Bakery photo", type: "IMAGE", selectable: false }], next_cursor: later ? null : "next" } });
    });
    await page.locator("#platform").selectOption("instagram");
    await page.getByText("Loading content…", { exact: true }).waitFor();
    await page.getByRole("button", { name: /Bakery photo/ }).waitFor();
    assert.equal(await page.getByRole("button", { name: /Bakery photo/ }).isDisabled(), true);
    await page.getByRole("button", { name: "Load more content" }).click();
    await page.getByRole("button", { name: /Weekend Reel/ }).click();
    assert.equal(await page.getByRole("button", { name: /Weekend Reel/ }).getAttribute("aria-pressed"), "true");
  }, { status: 200, json: { connected: true } });
});
