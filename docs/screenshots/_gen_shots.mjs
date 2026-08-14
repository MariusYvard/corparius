// The README screenshots, from the console that actually ships.
//
// English, forced before the first paint: the language is a localStorage preference and this machine
// runs in French, so the previous pass produced a French README hero. 1440x1000 at deviceScaleFactor
// 2 is 2880x2000, the same frame the old screenshots used — the point of the picture is what the
// console *is*, and changing its aspect at the same time would make the two hard to compare.
import { chromium } from 'playwright';
const [url, outDir] = process.argv.slice(2);
const browser = await chromium.launch();
for (const mode of ['dark', 'light']) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
  await ctx.addInitScript(() => {
    localStorage.setItem('corparius-lang', 'en');
    localStorage.setItem('corparius-tab', 'overview');
    localStorage.setItem('corparius-onboard-hidden', '1');
  });
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  await page.evaluate((m) => {
    const root = document.documentElement;
    if (m === 'light') root.setAttribute('data-theme', 'light');
    else root.removeAttribute('data-theme');
  }, mode);
  await page.waitForTimeout(900);
  const out = `${outDir}/console${mode === 'dark' ? '-dark' : ''}.png`;
  await page.screenshot({ path: out });
  const lang = await page.evaluate(() => document.documentElement.lang);
  console.log(mode, '->', out, 'lang=' + lang);
  await ctx.close();
}
await browser.close();
