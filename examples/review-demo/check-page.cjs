// Executes the actual page script in Node with a minimal DOM/storage harness.
// This is a behavior check, not a browser rendering or accessibility audit.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const path = require('node:path');
const page = process.argv[2];
const html = fs.readFileSync(page, 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
function load(saved = {}, blocked = false) {
  const root = {dataset: {theme: 'light'}};
  let click;
  const button = {textContent: '', attrs: {}, setAttribute(k,v) {this.attrs[k]=v;},
    addEventListener(kind, fn) {assert.equal(kind, 'click'); click=fn;}};
  const localStorage = {getItem(k) {if(blocked) throw Error('blocked'); return saved[k];},
    setItem(k,v) {if(blocked) throw Error('blocked'); saved[k]=v;}};
  vm.runInNewContext(script, {document: {documentElement: root,
    getElementById(id) {assert.equal(id, 'theme'); return button;}}, localStorage}, {timeout:1000});
  return {root, button, click: () => click()};
}
function state(app, theme) {
  assert.equal(app.root.dataset.theme, theme);
  assert.equal(app.button.attrs['aria-pressed'], String(theme === 'dark'));
  assert.equal(app.button.textContent, theme === 'dark' ? 'Hellmodus einschalten' : 'Dunkelmodus einschalten');
}
const saved = {};
const app = load(saved);
state(app, 'light'); app.click(); state(app, 'dark');
assert.equal(saved['kirabridge-theme'], 'dark');
state(load(saved), 'dark'); app.click(); state(app, 'light');
state(load(saved), 'light');
const restricted = load({}, true); state(restricted, 'light');
restricted.click(); state(restricted, 'dark');
state(load({'kirabridge-theme':'invalid'}), 'light');
assert.match(html, /:root\[data-theme="dark"\]/);
assert.match(html, /background: var\(--bg\)/);
assert.match(html, /<html lang="de"/);
assert.match(html, /type="button" aria-pressed="false"/);
const report = {passed:true, engine:process.version, kind:'Node VM with minimal DOM; no browser',
  page_sha256:crypto.createHash('sha256').update(fs.readFileSync(page)).digest('hex'),
  checks:['light to dark to light','aria-pressed and label','storage and reload both themes',
    'blocked storage','invalid stored value','theme CSS binding','German document and native button']};
fs.writeFileSync(path.join(path.dirname(page), 'checks.json'), JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
