// Minimal browser globals so the A2UI web components (Lit) can load under Node.
import {JSDOM} from 'jsdom';
const dom = new JSDOM('<!doctype html><html><body></body></html>', {url: 'http://localhost/'});
const g = globalThis as Record<string, unknown>;
for (const k of ['window', 'document', 'customElements', 'HTMLElement', 'Node', 'Element', 'CSSStyleSheet', 'ShadowRoot', 'Event', 'CustomEvent', 'MutationObserver', 'getComputedStyle', 'requestAnimationFrame', 'DOMParser', 'Document', 'HTMLTemplateElement', 'Text', 'Comment', 'DocumentFragment', 'TreeWalker', 'NodeFilter', 'HTMLStyleElement', 'KeyboardEvent', 'MouseEvent', 'FocusEvent', 'InputEvent', 'HTMLInputElement']) {
  if (!(k in g)) g[k] = (dom.window as unknown as Record<string, unknown>)[k];
}
g.navigator ??= dom.window.navigator;
