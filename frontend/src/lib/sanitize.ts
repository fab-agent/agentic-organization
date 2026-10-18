/**
 * HTML sanitizing for model, document and policy text (kept free of Svelte so it can
 * be tested). The caller passes a DOMPurify instance; if the instance cannot run,
 * every function falls back to escaped text, never to raw HTML.
 */
export type Purify = {
	isSupported: boolean;
	sanitize: (html: string, cfg?: Record<string, unknown>) => unknown;
};

export function escHtml(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;');
}

const SAFE = {
	ADD_ATTR: ['data-code', 'data-id', 'class', 'id', 'src', 'alt'],
	ADD_TAGS: ['details', 'summary', 'img'],
	FORCE_BODY: true,
	FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'object', 'embed', 'svg', 'math'],
	FORBID_ATTR: ['style', 'srcset']
};

const PREVIEW = {
	USE_PROFILES: { html: true },
	FORBID_TAGS: ['style', 'form', 'input', 'iframe', 'object', 'embed', 'img', 'svg', 'math', 'link', 'meta'],
	FORBID_ATTR: ['style', 'srcset', 'src', 'href']
};

const SVG = { USE_PROFILES: { svg: true, svgFilters: true } };

export function sanitizeHtml(purify: Purify, html: string): string {
	if (!purify.isSupported) return `<pre>${escHtml(html)}</pre>`;
	return String(purify.sanitize(html, SAFE));
}

export function previewHtml(purify: Purify, fragment: string): string {
	if (!purify.isSupported) return escHtml(fragment);
	return String(purify.sanitize(fragment, PREVIEW));
}

export function sanitizeSvg(purify: Purify, svg: string): string {
	if (!purify.isSupported) return '';
	return String(purify.sanitize(svg, SVG));
}
