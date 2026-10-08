/**
 * Recapture the portfolio screenshots in docs/screenshots/.
 *
 * Every shot is a real page render at a declared viewport, taken while signed in
 * as whichever demo account shows that surface best. Run against a live dev
 * server:  node scripts/capture_screenshots.mjs [baseUrl]
 */
import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const BASE = process.argv[2] ?? "http://127.0.0.1:5000";
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), "../docs/screenshots");

const DESKTOP = { width: 1440, height: 900 };
const LAPTOP = { width: 1920, height: 1080 };
const TABLET = { width: 768, height: 1024 };
const MOBILE = { width: 390, height: 844 };

const ACCOUNTS = {
  demo: ["demo@example.com", "demo12345"],
  employer: ["hr@gojek.com", "password123"],
  admin: ["admin@jobhunter.local", "admin123"],
};

/** path -> { viewport, name, account, expectStatus } */
const SHOTS = [
  { name: "01-home.png", path: "/", viewport: DESKTOP },
  { name: "02-search.png", path: "/jobs", viewport: DESKTOP },
  { name: "03-job-detail.png", path: "@firstJob", viewport: DESKTOP },
  { name: "04-matches.png", path: "/resume/matches", viewport: DESKTOP, account: "demo" },
  { name: "05-applications.png", path: "/applications", viewport: DESKTOP, account: "demo" },
  { name: "06-employer.png", path: "/employer", viewport: DESKTOP, account: "employer" },
  { name: "07-admin.png", path: "/admin", viewport: DESKTOP, account: "admin" },
  { name: "08-mobile.png", path: "/jobs", viewport: MOBILE, account: "demo" },
  // The 404 page is the subject here, so a 404 status is the expected result
  // and must not be counted as a capture failure.
  { name: "09-404.png", path: "/this-page-does-not-exist", viewport: DESKTOP, expectStatus: 404 },
  { name: "11-tablet.png", path: "/jobs", viewport: TABLET },
  { name: "12-alerts.png", path: "/alerts", viewport: DESKTOP, account: "demo" },
  { name: "13-applicants.png", path: "@firstPosting", viewport: DESKTOP, account: "employer" },
  { name: "14-about.png", path: "/about", viewport: DESKTOP },
  { name: "15-login.png", path: "/auth/login", viewport: DESKTOP },
  { name: "16-resume.png", path: "/resume", viewport: DESKTOP, account: "demo" },
  { name: "17-saved.png", path: "/saved", viewport: DESKTOP, account: "demo" },
  { name: "18-resume-preview.png", path: "/resume/preview", viewport: DESKTOP, account: "demo" },
  { name: "19-forgot-password.png", path: "/auth/forgot-password", viewport: DESKTOP },
  { name: "20-laptop.png", path: "/jobs", viewport: LAPTOP },
];

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch();
const consoleErrors = [];

/** Paths whose page is *supposed* to answer with an error status. */
const expectedErrorPaths = new Set(
  SHOTS.filter((s) => s.expectStatus && s.expectStatus >= 400).map((s) => new URL(s.path, BASE).pathname),
);

async function newContext(viewport) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    reducedMotion: "reduce",
  });
  context.on("page", (page) => {
    const label = () => new URL(page.url()).pathname;
    page.on("console", (msg) => {
      if (msg.type() !== "error") return;
      // A page that legitimately answers 404 (the error-page shot) will make the
      // browser log the failed request. That is the subject, not a defect.
      if (expectedErrorPaths.has(label())) return;
      consoleErrors.push(`${label()} :: ${msg.text()}`);
    });
    page.on("pageerror", (err) => consoleErrors.push(`${label()} :: ${err.message}`));
  });
  return context;
}

async function login(context, role) {
  const page = await context.newPage();
  await page.goto(`${BASE}/auth/login`, { waitUntil: "networkidle" });
  await page.fill("#login-email", ACCOUNTS[role][0]);
  await page.fill("#login-password", ACCOUNTS[role][1]);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle" }),
    page.click('button[type="submit"]'),
  ]);
  await page.close();
}

/** Resolve the "@firstJob" / "@firstPosting" placeholders from live data. */
async function resolvePlaceholders(context) {
  const page = await context.newPage();
  await page.goto(`${BASE}/jobs`, { waitUntil: "networkidle" });
  const firstJob = await page.getAttribute(".job-card-title", "href");
  await page.goto(`${BASE}/api/jobs?per_page=1`, { waitUntil: "domcontentloaded" });
  await page.close();
  return firstJob;
}

async function firstPostingPath(context) {
  const page = await context.newPage();
  await page.goto(`${BASE}/employer`, { waitUntil: "networkidle" });
  const href = await page.getAttribute("a[href^='/employer/jobs/']", "href").catch(() => null);
  await page.close();
  return href ?? "/employer";
}

const anonymous = await newContext(DESKTOP);
const jobPath = await resolvePlaceholders(anonymous);

const employerProbe = await newContext(DESKTOP);
await login(employerProbe, "employer");
const postingPath = await firstPostingPath(employerProbe);
await employerProbe.close();
await anonymous.close();

let captured = 0;
const failures = [];
for (const shot of SHOTS) {
  let path = shot.path;
  if (path === "@firstJob") path = jobPath;
  if (path === "@firstPosting") path = postingPath;

  const context = await newContext(shot.viewport);
  try {
    if (shot.account) await login(context, shot.account);
    const page = await context.newPage();
    const response = await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
    const expected = shot.expectStatus ?? 200;
    const status = response?.status() ?? 0;
    if (status !== expected) {
      failures.push(`${shot.name}: expected HTTP ${expected} for ${path}, got ${status}`);
    }
    // Let webfonts settle so text metrics are correct in the capture.
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: `${OUT}/${shot.name}`, fullPage: false });
    captured += 1;
    console.log(`  ok ${shot.name}  (${shot.viewport.width}x${shot.viewport.height}${shot.account ? `, as ${shot.account}` : ""})`);
    await page.close();
  } catch (error) {
    console.error(`  !! ${shot.name} -> ${error.message}`);
  } finally {
    await context.close();
  }
}

await browser.close();

console.log(`\n${captured}/${SHOTS.length} screenshots written to docs/screenshots/`);
if (failures.length) {
  console.log(`\nUnexpected page status (${failures.length}):`);
  for (const line of failures) console.log(`  ${line}`);
  process.exitCode = 1;
}
if (consoleErrors.length) {
  console.log(`\nConsole errors observed (${consoleErrors.length}):`);
  for (const line of [...new Set(consoleErrors)]) console.log(`  ${line}`);
  process.exitCode = 1;
} else {
  console.log("Every captured page returned its expected status, with no browser console errors.");
}
