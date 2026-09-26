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
    const page = await context.newPage();
    await page.goto(origin);
    await run(page, context);
  } finally { await browser.close(); }
}

async function fillInstagram(page, identifier = "17895695668004550") {
  await page.locator("#platform").selectOption("instagram");
  await page.locator("#video").setInputFiles({ name: "reel.mp4", mimeType: "video/mp4", buffer: Buffer.from("sample") });
  await page.locator("#meta-identifier").fill(identifier);
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
  }, { status: 200, json: { connected: true } });
});

test("Instagram rejects unsupported URLs and invalid IDs before uploading", async () => {
  await metaPage(async (page, context) => {
    let uploads = 0;
    await context.route("**/api/videos", (route) => { uploads++; return route.abort(); });
    await fillInstagram(page);
    for (const value of ["https://www.instagram.com/reel/abc/", "abc", "1".repeat(31), "   "]) {
      await page.locator("#meta-identifier").fill(value);
      await page.getByRole("button", { name: "Analyze video", exact: true }).click();
      await page.getByRole("alert").getByText(/Enter a numeric Instagram Graph media ID/).waitFor();
    }
    assert.equal(uploads, 0);
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
    });
  });
}
