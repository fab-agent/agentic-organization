import { test } from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import createDOMPurify from 'dompurify';
import { sanitizeHtml, previewHtml, sanitizeSvg, escHtml } from '../src/lib/sanitize.ts';

const purify = createDOMPurify(new JSDOM('').window);
const off = { isSupported: false, sanitize: () => '<img src=x onerror=alert(1)>' };

test('event handlers and scripts never survive', () => {
	for (const bad of [
		'<img src=x onerror=alert(1)>',
		'<script>alert(1)</script>',
		'<a href="javascript:alert(1)">x</a>',
		'<svg onload=alert(1)></svg>',
		'<iframe src="//evil"></iframe>',
		'<div style="background:url(//x)">y</div>'
	]) {
		const out = sanitizeHtml(purify, bad);
		assert.doesNotMatch(out, /onerror|onload|<script|javascript:|<iframe|<svg|style=/i, bad);
	}
});

test('ordinary markdown output is kept', () => {
	const out = sanitizeHtml(purify, '<p>Hi <strong>there</strong></p><ul><li>a</li></ul><details><summary>s</summary>b</details>');
	assert.match(out, /<strong>there<\/strong>/);
	assert.match(out, /<details>/);
});

test('the html preview is inert', () => {
	const out = previewHtml(purify, '<b>ok</b><img src="//x/y.png" onerror=1><a href="https://x">l</a><script>1</script>');
	assert.match(out, /<b>ok<\/b>/);
	assert.doesNotMatch(out, /<img|<script|href=|onerror/i);
});

test('mermaid svg is sanitized after rendering', () => {
	const out = sanitizeSvg(purify, '<svg xmlns="http://www.w3.org/2000/svg"><script>1</script><a xlink:href="javascript:1"><text>t</text></a></svg>');
	assert.doesNotMatch(out, /<script|javascript:/i);
});

test('without a working sanitizer text is escaped, never passed through', () => {
	assert.equal(sanitizeHtml(off, '<img src=x onerror=alert(1)>'), '<pre>&lt;img src=x onerror=alert(1)&gt;</pre>');
	assert.equal(previewHtml(off, '<b>x</b>'), '&lt;b&gt;x&lt;/b&gt;');
	assert.equal(sanitizeSvg(off, '<svg/>'), '');
	assert.equal(escHtml('"<&>'), '&quot;&lt;&amp;&gt;');
});
