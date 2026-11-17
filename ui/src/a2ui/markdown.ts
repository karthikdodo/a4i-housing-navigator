import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';

const md = new MarkdownIt({html: false, linkify: true, breaks: false});

// Record ids the agent cites. Rendered as chips the paralegal can click to open the record.
export const RECORD_ID = /\b(SF-\d{6,}|DECOY-[A-Z]{4}-\d{2}|STAT-[A-Z]{2}-\d{2}|BUL-[A-Z]{2}-\d{2})\b/g;

/** Markdown -> sanitized HTML. `chips` turns record ids into clickable citation chips. */
export function toHtml(text: string, opts: {inline?: boolean; chips?: boolean} = {}): string {
  let html = opts.inline ? md.renderInline(text ?? '') : md.render(text ?? '');
  if (opts.chips) {
    html = html.replace(RECORD_ID, id => `<button type="button" class="nv-chip" data-record="${id}">${id}</button>`);
  }
  return DOMPurify.sanitize(html, {ADD_ATTR: ['data-record', 'target']});
}

/** The A2UI basic catalog's Text component calls this (MarkdownContext). */
export async function renderMarkdown(text: string, options?: {renderMode?: 'inline' | 'block'}): Promise<string> {
  return toHtml(text, {inline: options?.renderMode === 'inline'});
}
