import { messages } from './messages.mjs';

const storageKey = 'openasrinput-language';
const canonical = (text) => text.replace(/\s+/g, ' ').trim();
let language;
try {
  language = localStorage.getItem(storageKey);
} catch {
  /* Private browsing. */
}
if (!['zh-CN', 'en'].includes(language))
  language = navigator.language?.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en';
const originals = new WeakMap();
const attributes = new WeakMap();
const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const patterns = Object.entries(messages)
  .filter(([key]) => key.includes('{'))
  .map(([key, value]) => {
    const names = [...key.matchAll(/\{(\d+)\}/g)].map((match) => match[1]);
    const pieces = key.split(/\{\d+\}/).map(escape);
    return { pattern: new RegExp('^' + pieces.join('([\\s\\S]*?)') + '$'), names, value };
  });

export function translate(text, depth = 0) {
  if (typeof text !== 'string' || language === 'zh-CN') return text;
  const key = canonical(text);
  let result = Object.hasOwn(messages, key) ? messages[key] : undefined;
  if (Array.isArray(result)) result = result[0];
  if (result === undefined) {
    for (const entry of patterns) {
      const match = entry.pattern.exec(key);
      if (match) {
        const [template, nested] = Array.isArray(entry.value) ? entry.value : [entry.value, []];
        result = template.replace(/\{(\d+)\}/g, (_, number) => {
          const value = match[entry.names.indexOf(number) + 1] ?? '';
          return nested.includes(Number(number)) && depth < 8 ? translate(value, depth + 1) : value;
        });
        break;
      }
    }
  }
  if (result === undefined && depth < 8 && / · |；|\n/.test(text)) {
    return text
      .split(/( · |；|\n)/)
      .map((part) =>
        /^( · |；|\n)$/.test(part) ? (part === '；' ? '; ' : part) : translate(part, depth + 1)
      )
      .join('');
  }
  return result === undefined ? text : text.match(/^\s*/)[0] + result + text.match(/\s*$/)[0];
}

export function sourceText(element) {
  return [...element.childNodes]
    .map((node) => originals.get(node)?.source ?? node.textContent)
    .join('');
}

export function userOption(title, value) {
  const option = new Option(title, value);
  option.translate = false;
  return option;
}

export function userText(value) {
  const span = document.createElement('span');
  span.translate = false;
  span.textContent = value;
  return span;
}

export const confirm = (message) => window.confirm(translate(message));
export const prompt = (message, value) => window.prompt(translate(message), value);
export const currentLanguage = () => language;

function textNode(node) {
  if (
    !node.parentElement ||
    node.parentElement.closest('script,style,textarea,[translate="no"],[data-user-content]')
  )
    return;
  let record = originals.get(node);
  if (!record || node.data !== record.output) record = { source: node.data };
  record.output = translate(record.source);
  originals.set(node, record);
  if (node.data !== record.output) node.data = record.output;
}

function element(node) {
  if (node.closest('[translate="no"],[data-user-content]')) return;
  const saved = attributes.get(node) || {};
  for (const name of ['title', 'placeholder', 'aria-label', 'alt']) {
    if (!node.hasAttribute(name)) continue;
    const value = node.getAttribute(name);
    let record = saved[name];
    if (!record || value !== record.output) record = { source: value };
    record.output = translate(record.source);
    saved[name] = record;
    if (value !== record.output) node.setAttribute(name, record.output);
  }
  attributes.set(node, saved);
}

function render(root = document.documentElement) {
  if (root.nodeType === Node.TEXT_NODE) return textNode(root);
  if (root.nodeType !== Node.ELEMENT_NODE) return;
  if (root.closest('script,style,[translate="no"],[data-user-content]')) return;
  element(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    if (walker.currentNode.nodeType === Node.TEXT_NODE) textNode(walker.currentNode);
    else element(walker.currentNode);
  }
}

function select(value, persist = true) {
  if (!['zh-CN', 'en'].includes(value)) return;
  language = value;
  document.documentElement.lang = value;
  if (persist) {
    try {
      localStorage.setItem(storageKey, value);
    } catch {
      /* Keep this tab usable. */
    }
  }
  document
    .querySelectorAll('[data-language]')
    .forEach((button) =>
      button.setAttribute('aria-pressed', String(button.dataset.language === value))
    );
  render();
  document.dispatchEvent(new CustomEvent('languagechange', { detail: value }));
}

document
  .querySelectorAll('[data-language]')
  .forEach((button) => button.addEventListener('click', () => select(button.dataset.language)));
window.addEventListener('storage', (event) => {
  if (event.key === storageKey && event.newValue) select(event.newValue, false);
});
select(language, false);
new MutationObserver((changes) => {
  for (const change of changes) {
    if (change.type === 'childList') change.addedNodes.forEach(render);
    else render(change.target);
  }
}).observe(document.documentElement, {
  subtree: true,
  childList: true,
  characterData: true,
  attributes: true,
  attributeFilter: ['title', 'placeholder', 'aria-label', 'alt', 'translate']
});
