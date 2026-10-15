const fs = require('fs');
const els = {};
function mkEl(id) {
  return { id, dataset: {}, textContent: '', innerHTML: '', value: '', placeholder: '', title: '',
    checked: false, classList: { add(){}, remove(){}, toggle(){}, contains:()=>false },
    style: {}, onclick: null, onchange: null, options: [], clientWidth: 600,
    addEventListener(){}, appendChild(){}, click(){}, focus(){},
    getContext: () => new Proxy({}, { get: () => () => ({}) , set: () => true }) };
}
global.document = {
  documentElement: { lang: '' },
  querySelector: () => null,
  querySelectorAll: () => [],
  getElementById: (id) => els[id] || (els[id] = mkEl(id)),
  createElement: () => mkEl('x'),
  addEventListener: () => {},
};
global.localStorage = { _s: {}, getItem(k){return this._s[k]||null}, setItem(k,v){this._s[k]=v} };
global.sessionStorage = { getItem:()=>null, setItem(){}, removeItem(){} };
global.navigator = { clipboard: { writeText: () => Promise.resolve() } };
global.location = { hash: '', origin: 'http://x', href: '' };
global.history = { replaceState: () => {} };
global.fetch = () => Promise.reject(new Error('offline'));
global.crypto = { subtle: { digest: async () => new Uint8Array(32) } };
global.window = { addEventListener: () => {}, devicePixelRatio: 1 };
global.setInterval = () => 0;
global.__els = els;
const src = fs.readFileSync('prof/console/i18n.js','utf8') + '\n' + fs.readFileSync('prof/console/app.js','utf8') + `
;setLang('ko');
if (document.documentElement.lang !== 'ko') throw new Error('lang not applied');
renderScenarios();
if (__els['verify-mini'].innerHTML.indexOf('정상 요청') < 0) throw new Error('KO render broken');
setLang('en');
applyLang('ko');
if (__els['verify-mini'].innerHTML.indexOf('정상 요청') < 0) throw new Error('applyLang ko broken');
applyLang('en');
if (__els['verify-mini'].innerHTML.indexOf('Legit request') < 0) throw new Error('EN render broken');
if (localStorage.getItem('prof_lang') !== 'en') throw new Error('persistence broken');
console.log('HARNESS OK — boot + KO/EN render + persistence, no exceptions');`;
eval(src);
