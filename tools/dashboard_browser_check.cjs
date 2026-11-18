#!/usr/bin/env node
/* Optional Playwright E2E acceptance for an already generated AIQE dashboard.
 *
 * No application server and no network access are required. The script reads
 * only an explicit HTML file and writes screenshots/report JSON to an explicit
 * output directory. Playwright is a development tool, not an AIQE dependency.
 */

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`missing ${name}`);
  return process.argv[index + 1];
}

async function main() {
  const input = path.resolve(argument("--input"));
  const out = path.resolve(argument("--out"));
  const label = process.argv.includes("--label")
    ? process.argv[process.argv.indexOf("--label") + 1]
    : "dashboard";
  fs.mkdirSync(out, { recursive: true });
  const launchOptions = { headless: true };
  if (process.env.AIQE_CHROME_EXECUTABLE) {
    launchOptions.executablePath = process.env.AIQE_CHROME_EXECUTABLE;
  } else {
    launchOptions.channel = process.env.AIQE_CHROME_CHANNEL || "chrome";
  }
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const jsErrors = [];
  const externalRequests = [];
  const checks = [];
  const screenshots = [];
  page.on("pageerror", error => jsErrors.push(String(error)));
  page.on("request", request => {
    if (/^https?:/.test(request.url())) externalRequests.push(request.url());
  });
  async function check(name, fn) {
    await fn();
    checks.push({ name, status: "PASS" });
  }
  async function screenshot(name, locator) {
    screenshots.push(name);
    if (locator) {
      // Sticky controls otherwise cover the middle of tall element screenshots.
      await page.locator(".topbar").evaluate(element => { element.style.visibility = "hidden"; });
      await page.locator(locator).screenshot({ path: path.join(out, name) });
      await page.locator(".topbar").evaluate(element => { element.style.visibility = ""; });
    } else {
      await page.screenshot({ path: path.join(out, name), fullPage: true });
    }
  }
  function writeReport(status, dataSummary) {
    const report = {
      report_version: "aiqe.dashboard-browser-check/0.1.0",
      label,
      input,
      status,
      checks,
      data_summary: dataSummary || null,
      js_errors: jsErrors,
      external_requests: externalRequests,
      screenshots: screenshots.slice().sort(),
    };
    fs.writeFileSync(
      path.join(out, "browser-report.json"),
      JSON.stringify(report, null, 2) + "\n",
    );
  }

  let dataSummary = null;
  try {
    await page.goto(pathToFileURL(input).href, { waitUntil: "load" });
    await check("product title", async () => assert.match(await page.title(), /AIQE Dashboard/));
    const initial = await page.evaluate(() => ({
      sections: document.querySelectorAll("main section").length,
      scaleCards: document.querySelectorAll("#explorer-scale .scale-item").length,
      capabilities: document.querySelectorAll("#explorer-capabilities .capability-card").length,
      overflow: document.documentElement.scrollWidth > innerWidth,
      bodyText: document.body.innerText,
      payload: JSON.parse(document.getElementById("aiqe-data").textContent),
    }));
    dataSummary = {
      run_count: initial.payload.totals.run_count,
      group_count: initial.payload.totals.group_count,
      unreadable_count: initial.payload.totals.unreadable_count,
      case_execution_count: initial.payload.analysis.scale.case_execution_count,
      source_types: [...new Set(initial.payload.runs.map(run => run.source_type))].sort(),
      data_classifications: [...new Set(initial.payload.runs.map(run => run.data_classification))].sort(),
    };
    await check("five quality regions", () => assert.equal(initial.sections, 5));
    await check("six evidence scale cards", () => assert.equal(initial.scaleCards, 6));
    await check("two explicit capability gaps", () => assert.equal(initial.capabilities, 2));
    await check("capability gaps do not invent zero metrics", () => {
      assert.match(initial.bodyText, /unavailable/);
      assert.match(initial.bodyText, /通过率与评分不能替代幻觉率/);
      assert.match(initial.bodyText, /无法还原调用栈/);
    });
    await check("desktop has no page-level horizontal overflow", () => assert.equal(initial.overflow, false));
    await check("no NaN or Infinity is rendered", () => {
      assert.doesNotMatch(initial.bodyText, /\bNaN\b|\bInfinity\b/);
    });
    if (dataSummary.source_types.some(source => source !== "synthetic")) {
      await check("non-synthetic source warning remains visible", async () => {
        assert.ok(await page.locator("#b-src.real").count());
        assert.match(await page.locator("#provenance").innerText(), /禁止提交入库/);
      });
    } else {
      await check("sharing warning is hidden without non-synthetic runs", async () => {
        assert.equal(await page.locator("#b-sharing").isHidden(), true);
        assert.equal(await page.locator("#b-src.real").count(), 0);
      });
    }

    const dimensions = await page.locator("#explorer-dimension option").evaluateAll(options =>
      options.map(option => ({ value: option.value, label: option.textContent })),
    );
    for (const dimension of dimensions) {
      await page.selectOption("#explorer-dimension", dimension.value);
      const rendered = await page.evaluate(() => ({
        caption: document.querySelector("#explorer-pivot caption").textContent,
        subtitle: document.getElementById("explorer-bars-sub").textContent,
        rows: document.querySelectorAll("#explorer-pivot tbody tr").length,
        text: document.getElementById("explorer").innerText,
      }));
      await check(`dimension ${dimension.value} updates chart and pivot`, () => {
        assert.match(rendered.caption, new RegExp(dimension.label));
        assert.match(rendered.subtitle, new RegExp(dimension.label));
        assert.ok(rendered.rows > 0);
        assert.doesNotMatch(rendered.text, /\bNaN\b|\bInfinity\b/);
      });
    }
    await page.selectOption("#explorer-dimension", "model");
    await screenshot("explorer-light.png", "#explorer");

    await page.click("#theme-toggle");
    await check("dark theme is applied", async () => {
      assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
      assert.equal(await page.locator("#theme-toggle").getAttribute("aria-pressed"), "true");
    });
    await screenshot("explorer-dark.png", "#explorer");
    await page.click("#theme-toggle");
    await check("light theme is restored", async () => {
      assert.equal(await page.locator("html").getAttribute("data-theme"), "light");
    });

    const trendPoints = await page.locator(".trend-point").count();
    if (trendPoints) {
      await page.locator(".trend-point").first().focus();
      await check("trend keyboard focus exposes an exact reading", async () => {
        assert.equal(await page.locator("#trend-tip").getAttribute("hidden"), null);
        assert.ok((await page.locator("#trend-tip").innerText()).length > 0);
      });
    } else {
      checks.push({ name: "trend keyboard focus", status: "SKIP", reason: "no plottable points" });
    }
    await check("comparison controls render a verdict or empty state", async () => {
      assert.ok((await page.locator("#cmp-body").innerText()).length > 0);
    });
    await check("print control is available", async () => {
      assert.equal(await page.locator("#print-button").count(), 1);
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#explorer").scrollIntoViewIfNeeded();
    const mobile = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth > innerWidth,
      selectorVisible: !!document.getElementById("explorer-dimension").offsetParent,
      pivotLocalScroll: document.getElementById("explorer-pivot").scrollWidth >=
        document.getElementById("explorer-pivot").clientWidth,
    }));
    await check("390px mobile has no page-level horizontal overflow", () => {
      assert.equal(mobile.overflow, false);
      assert.equal(mobile.selectorVisible, true);
      assert.equal(mobile.pivotLocalScroll, true);
    });
    await page.screenshot({ path: path.join(out, "explorer-mobile.png") });
    screenshots.push("explorer-mobile.png");
    await page.setViewportSize({ width: 1440, height: 1100 });

    await check("no JavaScript page errors", () => assert.deepEqual(jsErrors, []));
    await check("no external HTTP requests", () => assert.deepEqual(externalRequests, []));
    writeReport("PASS", dataSummary);
    console.log(JSON.stringify({ status: "PASS", label, checks: checks.length, out }, null, 2));
  } catch (error) {
    checks.push({ name: "browser execution", status: "FAIL", message: String(error) });
    try {
      await page.screenshot({ path: path.join(out, "failure.png"), fullPage: true });
      screenshots.push("failure.png");
    } catch (_) {}
    writeReport("FAIL", dataSummary);
    throw error;
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
