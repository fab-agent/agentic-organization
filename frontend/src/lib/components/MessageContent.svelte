<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { marked, Renderer, type Tokens } from 'marked';
	import DOMPurify from 'dompurify';
	import { escHtml, previewHtml as previewHtmlSafe, sanitizeHtml, sanitizeSvg } from '$lib/sanitize';

	let { content, streaming = false }: { content: string; streaming?: boolean } = $props();

	let containerEl = $state<HTMLDivElement | null>(null);
	let rendered = $state('');
	let mermaidReady = $state(false);
	let copiedMap = $state<Record<string, boolean>>({});

	const sanitize = (html: string) => sanitizeHtml(DOMPurify, html);
	const previewHtml = (fragment: string) => previewHtmlSafe(DOMPurify, fragment);

	// ── Custom marked renderer ────────────────────────────────────────────────
	function buildRenderer() {
		const r = new Renderer();

		r.code = function (token: Tokens.Code) {
			const { text, lang } = token;
			const language = (lang || '').toLowerCase().trim();

			if (language === 'mermaid') {
				const id = `mmd-${Math.random().toString(36).slice(2, 9)}`;
				return `<div class="mermaid-wrap" data-code="${encodeURIComponent(text)}" data-id="${id}">
					<div class="mermaid-pending" id="${id}">
						<div class="mermaid-spinner"></div>
					</div>
				</div>`;
			}

			if (language === 'html') {
				const previewId = `html-prev-${Math.random().toString(36).slice(2, 9)}`;
				return `<div class="code-wrap html-wrap">
					<div class="code-header">
						<span class="lang-badge">html</span>
						<button class="copy-btn" data-code="${encodeURIComponent(text)}"><span class="copy-label">Kopyala</span></button>
					</div>
					<pre class="code-block"><code class="lang-html">${escHtml(text)}</code></pre>
					<details class="html-preview">
						<summary>
							<span>HTML Önizleme</span>
						</summary>
						<div class="html-render" id="${previewId}">${previewHtml(text)}</div>
					</details>
				</div>`;
			}

			if (language === 'json') {
				let formatted = text;
				try {
					formatted = JSON.stringify(JSON.parse(text), null, 2);
				} catch {}
				return `<div class="code-wrap json-wrap">
					<div class="code-header">
						<span class="lang-badge">json</span>
						<button class="copy-btn" data-code="${encodeURIComponent(text)}"><span class="copy-label">Kopyala</span></button>
					</div>
					<pre class="code-block json-block"><code>${escHtml(formatted)}</code></pre>
				</div>`;
			}

			return `<div class="code-wrap">
				<div class="code-header">
					<span class="lang-badge">${escHtml(language || 'code')}</span>
					<button class="copy-btn" data-code="${encodeURIComponent(text)}"><span class="copy-label">Kopyala</span></button>
				</div>
				<pre class="code-block"><code class="lang-${escHtml(language)}">${escHtml(text)}</code></pre>
			</div>`;
		};

		return r;
	}

	// ── Render pipeline ───────────────────────────────────────────────────────
	function renderMarkdown(text: string): string {
		if (!text) return '';

		// Detect raw JSON (no markdown)
		if (text.trim().startsWith('{') || text.trim().startsWith('[')) {
			try {
				const obj = JSON.parse(text);
				const formatted = JSON.stringify(obj, null, 2);
				return `<div class="code-wrap json-wrap">
					<div class="code-header">
						<span class="lang-badge">json</span>
						<button class="copy-btn" data-code="${encodeURIComponent(text)}"><span class="copy-label">Kopyala</span></button>
					</div>
					<pre class="code-block json-block"><code>${escHtml(formatted)}</code></pre>
				</div>`;
			} catch {}
		}

		marked.use({
			renderer: buildRenderer(),
			breaks: true,
			gfm: true,
		});

		const raw = marked.parse(text) as string;
		return sanitize(raw);
	}

	// ── Mermaid initialization ────────────────────────────────────────────────
	async function initMermaid() {
		if (typeof window === 'undefined') return;
		const mermaid = (await import('mermaid')).default;
		mermaid.initialize({
			startOnLoad: false,
			theme: document.documentElement.classList.contains('dark') ? 'dark' : 'default',
			fontFamily: 'inherit',
			securityLevel: 'strict',
		});
		mermaidReady = true;
	}

	async function renderMermaidBlocks() {
		if (!containerEl || !mermaidReady) return;
		const mermaid = (await import('mermaid')).default;

		const blocks = containerEl.querySelectorAll<HTMLElement>('.mermaid-wrap[data-code]');
		for (const block of blocks) {
			const code = decodeURIComponent(block.getAttribute('data-code') || '');
			const id = block.getAttribute('data-id') || `mmd-${Date.now()}`;
			const target = block.querySelector<HTMLElement>('.mermaid-pending');
			if (!target || target.getAttribute('data-rendered') === 'true') continue;

			try {
				const { svg } = await mermaid.render(`${id}-svg`, code);
				target.innerHTML = sanitizeSvg(DOMPurify, svg);
				target.setAttribute('data-rendered', 'true');
				target.className = 'mermaid-rendered';
			} catch (e) {
				target.innerHTML = `<pre class="mermaid-error">${escHtml(code)}</pre>`;
				target.setAttribute('data-rendered', 'true');
			}
		}
	}

	// ── Copy button logic ─────────────────────────────────────────────────────
	function attachCopyHandlers() {
		if (!containerEl) return;
		containerEl.querySelectorAll<HTMLButtonElement>('.copy-btn').forEach((btn) => {
			btn.addEventListener('click', async (e) => {
				e.stopPropagation();
				const code = decodeURIComponent(btn.getAttribute('data-code') || '');
				await navigator.clipboard.writeText(code);
				const label = btn.querySelector('.copy-label');
				if (label) {
					label.textContent = 'Kopyalandı!';
					setTimeout(() => { label.textContent = 'Kopyala'; }, 1800);
				}
			});
		});
	}

	// ── DOMPurify lazy load ───────────────────────────────────────────────────
	onMount(async () => {
		await initMermaid();
	});

	$effect(() => {
		rendered = renderMarkdown(content);
		tick().then(async () => {
			attachCopyHandlers();
			await renderMermaidBlocks();
		});
	});
</script>

<div bind:this={containerEl} class="msg-content {streaming ? 'streaming' : ''}">
	{@html rendered}
</div>

<style>
	.msg-content {
		font-size: 0.875rem;
		line-height: 1.65;
		color: var(--foreground, #111);
		word-break: break-word;
	}

	.msg-content :global(p) { margin: 0.35em 0; }
	.msg-content :global(p:first-child) { margin-top: 0; }
	.msg-content :global(p:last-child) { margin-bottom: 0; }

	.msg-content :global(h1),
	.msg-content :global(h2),
	.msg-content :global(h3),
	.msg-content :global(h4) {
		font-weight: 600;
		margin: 0.9em 0 0.3em;
		line-height: 1.3;
	}
	.msg-content :global(h1) { font-size: 1.2em; }
	.msg-content :global(h2) { font-size: 1.1em; }
	.msg-content :global(h3) { font-size: 1em; }

	.msg-content :global(ul),
	.msg-content :global(ol) {
		padding-left: 1.4em;
		margin: 0.35em 0;
	}
	.msg-content :global(li) { margin: 0.15em 0; }

	.msg-content :global(blockquote) {
		border-left: 3px solid hsl(var(--primary));
		padding: 0.3em 0.8em;
		margin: 0.5em 0;
		color: hsl(var(--muted-foreground));
		background: hsl(var(--muted) / 0.4);
		border-radius: 0 6px 6px 0;
	}

	.msg-content :global(strong) { font-weight: 600; }
	.msg-content :global(em) { font-style: italic; }

	.msg-content :global(a) {
		color: hsl(var(--primary));
		text-decoration: underline;
		text-underline-offset: 2px;
	}

	.msg-content :global(hr) {
		border: none;
		border-top: 1px solid hsl(var(--border));
		margin: 0.8em 0;
	}

	/* Inline code */
	.msg-content :global(code:not(pre code)) {
		background: hsl(var(--muted));
		border-radius: 4px;
		padding: 0.15em 0.4em;
		font-size: 0.82em;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
	}

	/* Code wrap */
	.msg-content :global(.code-wrap) {
		margin: 0.6em 0;
		border-radius: 10px;
		overflow: hidden;
		border: 1px solid hsl(var(--border));
		background: hsl(var(--muted) / 0.3);
	}

	.msg-content :global(.code-header) {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.35em 0.75em;
		background: hsl(var(--muted) / 0.5);
		border-bottom: 1px solid hsl(var(--border));
	}

	.msg-content :global(.lang-badge) {
		font-size: 0.72em;
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: hsl(var(--muted-foreground));
		font-family: monospace;
	}

	.msg-content :global(.copy-btn) {
		font-size: 0.72em;
		padding: 0.2em 0.55em;
		border-radius: 5px;
		border: 1px solid hsl(var(--border));
		background: hsl(var(--background));
		cursor: pointer;
		color: hsl(var(--muted-foreground));
		transition: background 0.15s;
	}
	.msg-content :global(.copy-btn:hover) {
		background: hsl(var(--muted));
		color: hsl(var(--foreground));
	}

	.msg-content :global(.code-block) {
		margin: 0;
		padding: 0.75em 1em;
		overflow-x: auto;
		font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
		font-size: 0.8em;
		line-height: 1.6;
		tab-size: 2;
		background: transparent;
	}

	.msg-content :global(.code-block code) {
		background: none;
		padding: 0;
		border-radius: 0;
		font-size: 1em;
	}

	/* JSON specific */
	.msg-content :global(.json-block) {
		color: hsl(160 60% 45%);
	}

	/* HTML preview */
	.msg-content :global(.html-preview) {
		border-top: 1px solid hsl(var(--border));
	}

	.msg-content :global(.html-preview summary) {
		padding: 0.35em 0.75em;
		font-size: 0.75em;
		font-weight: 500;
		cursor: pointer;
		background: hsl(var(--muted) / 0.4);
		color: hsl(var(--muted-foreground));
		user-select: none;
	}

	.msg-content :global(.html-render) {
		padding: 0.75em 1em;
		background: hsl(var(--background));
		font-size: 0.9em;
	}

	/* Mermaid */
	.msg-content :global(.mermaid-wrap) {
		margin: 0.6em 0;
		border-radius: 10px;
		border: 1px solid hsl(var(--border));
		overflow: hidden;
	}

	.msg-content :global(.mermaid-pending) {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 80px;
		background: hsl(var(--muted) / 0.2);
	}

	.msg-content :global(.mermaid-rendered) {
		padding: 1em;
		background: hsl(var(--background));
		display: flex;
		justify-content: center;
	}

	.msg-content :global(.mermaid-rendered svg) {
		max-width: 100%;
		height: auto;
	}

	.msg-content :global(.mermaid-error) {
		padding: 0.75em;
		font-size: 0.75em;
		color: hsl(var(--destructive));
		white-space: pre-wrap;
	}

	.msg-content :global(.mermaid-spinner) {
		width: 20px;
		height: 20px;
		border: 2px solid hsl(var(--border));
		border-top-color: hsl(var(--primary));
		border-radius: 50%;
		animation: spin 0.7s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	/* Generated images */
	.msg-content :global(img) {
		max-width: 100%;
		border-radius: 10px;
		border: 1px solid hsl(var(--border));
		margin: 0.5em 0;
		display: block;
	}

	/* Tables */
	.msg-content :global(table) {
		border-collapse: collapse;
		width: 100%;
		font-size: 0.85em;
		margin: 0.5em 0;
	}
	.msg-content :global(th),
	.msg-content :global(td) {
		border: 1px solid hsl(var(--border));
		padding: 0.4em 0.7em;
		text-align: left;
	}
	.msg-content :global(th) {
		background: hsl(var(--muted) / 0.5);
		font-weight: 600;
	}
	.msg-content :global(tr:nth-child(even) td) {
		background: hsl(var(--muted) / 0.2);
	}
</style>
