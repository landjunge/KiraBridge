// A fresh browser and profile owned only by this acceptance run.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.KIRABRIDGE_PLAYWRIGHT_MODULE || 'playwright');
const pageFile = path.resolve(process.argv[2]);
const output = path.resolve(process.argv[3]);
fs.mkdirSync(output, {recursive:true});
const html = fs.readFileSync(pageFile);
const report = {passed:false, kind:'real Chromium browser',
  page_sha256:crypto.createHash('sha256').update(html).digest('hex'), checks:[]};
const server = http.createServer((req,res) => {
  if (req.url === '/favicon.ico') {res.writeHead(204).end(); return;}
  if (req.url !== '/') {res.writeHead(404).end(); return;}
  res.writeHead(200, {'Content-Type':'text/html; charset=utf-8'}); res.end(html);
});
let browser;
(async () => {
  await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({headless:true,
    ...(process.env.KIRABRIDGE_CHROMIUM ? {executablePath:process.env.KIRABRIDGE_CHROMIUM} : {})});
  report.browser_version = browser.version();
  const context = await browser.newContext({viewport:{width:1280,height:900}});
  await context.route('**/*', route => route.request().url().startsWith(origin+'/')
    ? route.continue() : route.abort());
  const page = await context.newPage();
  const errors=[];
  page.on('pageerror', error => errors.push(String(error)));
  await page.goto(origin, {waitUntil:'networkidle', timeout:15000});
  const button = page.locator('#theme');
  await button.waitFor({state:'visible'});
  assert.equal(await button.getAttribute('type'), 'button');
  assert.equal(await button.getAttribute('aria-pressed'), 'false');
  assert.equal(await page.locator('html').getAttribute('lang'), 'de');
  const background = () => page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor);
  const light = await background();
  await page.screenshot({path:path.join(output,'desktop-light.png'),fullPage:true});
  await button.click();
  assert.equal(await button.getAttribute('aria-pressed'), 'true');
  const dark = await background(); assert.notEqual(dark,light);
  assert.equal(await page.evaluate(() => localStorage.getItem('kirabridge-theme')), 'dark');
  await page.reload(); assert.equal(await button.getAttribute('aria-pressed'), 'true');
  assert.equal(await background(),dark);
  await page.screenshot({path:path.join(output,'desktop-dark.png'),fullPage:true});
  await button.focus(); await page.keyboard.press('Enter');
  assert.equal(await button.getAttribute('aria-pressed'),'false');
  assert.equal(await background(),light);
  await page.reload(); assert.equal(await button.getAttribute('aria-pressed'),'false');
  await button.focus(); await page.keyboard.press('Space');
  assert.equal(await button.getAttribute('aria-pressed'),'true');
  assert.equal(await background(),dark);
  report.checks.push('mouse changes rendered theme','aria-pressed follows state',
    'localStorage and reload both themes','Enter and Space operate native button');
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({path:path.join(output,'mobile-dark.png'),fullPage:true});
  report.checks.push('390px viewport without horizontal overflow');
  assert.deepEqual(errors,[]);
  const restricted = await browser.newContext({viewport:{width:390,height:844}});
  await restricted.route('**/*', route => route.request().url().startsWith(origin+'/')
    ? route.continue() : route.abort());
  await restricted.addInitScript(() => {
    Storage.prototype.getItem = () => {throw new DOMException('Blocked','SecurityError');};
    Storage.prototype.setItem = () => {throw new DOMException('Blocked','SecurityError');};
  });
  const locked = await restricted.newPage();
  locked.on('pageerror', error => errors.push(String(error)));
  await locked.goto(origin,{waitUntil:'networkidle', timeout:15000});
  await locked.locator('#theme').click();
  assert.equal(await locked.locator('#theme').getAttribute('aria-pressed'),'true');
  await locked.locator('#theme').click();
  assert.equal(await locked.locator('#theme').getAttribute('aria-pressed'),'false');
  assert.deepEqual(errors,[]);
  report.checks.push('blocked storage keeps switch usable','no page JavaScript errors');
  report.passed=true;
})().catch(error => {report.error=String(error); process.exitCode=1;})
  .finally(async () => {
    if(browser) await browser.close();
    server.close();
    fs.writeFileSync(path.join(output,'browser-checks.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report));
  });
