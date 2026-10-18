<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { assistantApi, type AssistantContext } from '$lib/api/assistant';
	import { outputsApi, isRisky, type OutputFile } from '$lib/api/outputs';
	import { sessionsApi, streamMessage, type Attachment } from '$lib/api/sessions';
	import { companyStore } from '$lib/stores/company.svelte';
	import MessageContent from '$lib/components/MessageContent.svelte';
	import Button from '$lib/components/ui/button.svelte';
	import { Loader, Paperclip, Send, X } from '@lucide/svelte';

	type Source = { kind: string; date: string; snippet: string };
	type Turn = { role: 'user' | 'assistant'; content: string; sources?: Source[] };

	let ctx: AssistantContext | null = $state(null);
	let error: string | null = $state(null);
	let sessionId: string | null = $state(null);
	let turns: Turn[] = $state([]);
	let draft = $state('');
	let streaming = $state(false);
	let streamingText = $state('');
	let status = $state('');
	let attachments: Attachment[] = $state([]);
	let fileInput: HTMLInputElement | undefined = $state();
	let scroller: HTMLDivElement | undefined = $state();

	const activeCompanyId = $derived(companyStore.active?.id ?? '');
	const canChat = $derived(((c: AssistantContext | null) => !!c?.agent && c.agent.status === 'active')(ctx));

	let outputs: { id: string; files: OutputFile[] } | null = $state(null);
	let generation = 0;
	// Bumped by every reset: any create/upload/send that started before it is stale.
	let epoch = 0;
	let abort: AbortController | null = null;
	let loadedFor = '';

	/** A chat belongs to one company and one agent: switching drops all of it. */
	function reset() {
		epoch++;
		abort?.abort();
		abort = null;
		sessionId = null;
		turns = [];
		draft = '';
		attachments = [];
		streaming = false;
		streamingText = '';
		status = '';
		ctx = null;
		outputs = null;
	}

	async function load() {
		const mine = ++generation;
		const company = activeCompanyId;
		try {
			const next = await assistantApi.context(company || undefined);
			if (mine !== generation) return; // a newer load or a company switch won
			ctx = next;
			outputs = await outputsApi.list(company || undefined);
			if (mine !== generation) return;
			loadedFor = company;
			error = null;
		} catch (e) {
			if (mine !== generation) return;
			ctx = null;
			error = (e as Error).message;
		}
	}
	onMount(load);
	$effect(() => {
		const company = activeCompanyId;
		if (!company || company === loadedFor) return;
		if (loadedFor) reset();
		load();
	});

	async function toBottom() {
		await tick();
		scroller?.scrollTo({ top: scroller.scrollHeight });
	}

	async function pickFile(e: Event) {
		const f = (e.target as HTMLInputElement).files?.[0];
		if (!f) return;
		const mine = epoch;
		try {
			let sid = sessionId;
			if (!sid && ctx?.agent) {
				const created = (await sessionsApi.create(ctx.agent.id)).id;
				if (mine !== epoch) return; // the company changed while we waited
				sessionId = sid = created;
			}
			if (sid) {
				const att = await sessionsApi.uploadFile(sid, f);
				if (mine !== epoch) return;
				attachments = [...attachments, att];
			}
		} catch (err) {
			if (mine === epoch) error = (err as Error).message;
		} finally {
			if (fileInput) fileInput.value = '';
		}
	}

	async function send() {
		const text = draft.trim();
		if ((!text && !attachments.length) || streaming || !ctx?.agent || ctx.agent.status !== 'active') return;
		const mine = epoch;
		error = null;
		let sid = sessionId;
		try {
			if (!sid) {
				const created = (await sessionsApi.create(ctx.agent.id)).id;
				if (mine !== epoch) return;
				sessionId = sid = created;
			}
		} catch (e) {
			if (mine === epoch) error = (e as Error).message;
			return;
		}
		turns = [...turns, { role: 'user', content: text }];
		const sent = attachments;
		draft = '';
		attachments = [];
		streaming = true;
		streamingText = '';
		const ctl = new AbortController();
		abort = ctl;
		status = 'Düşünüyor…';
		await toBottom();
		let answer = '';
		let cited: Source[] = [];
		try {
			for await (const ev of streamMessage(sid, text, ctl.signal, sent)) {
				if (mine !== epoch) break; // the company changed under us
				if (ev.type === 'text') {
					answer += ev.content;
					streamingText = answer;
				} else if (ev.type === 'status') {
					status = ev.step === 'tool' ? `Çalışıyor: ${ev.name}` : `Tamamlandı: ${ev.name}${ev.ok === false ? ' (hata)' : ''}`;
				} else if (ev.type === 'sources') {
					cited = ev.items;
				} else if (ev.type === 'error') error = ev.message;
				else if (ev.type === 'done' || ev.type === 'stream_end') break;
				await toBottom();
			}
		} catch (e) {
			if (mine === epoch) error = (e as Error).message;
		} finally {
			// Only the generation that started this send may touch the shared state.
			if (mine === epoch) {
				if (answer) turns = [...turns, { role: 'assistant', content: answer, sources: cited }];
				streamingText = '';
				streaming = false;
				status = '';
				await toBottom();
			}
		}
	}

	function onKey(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			send();
		}
	}
</script>

<svelte:head><title>Asistan • fab.engineering</title></svelte:head>

<div class="grid gap-4 lg:grid-cols-[1fr_20rem] h-[calc(100vh-8rem)]">
	<section class="flex flex-col min-h-0 rounded-xl border">
		<header class="px-4 py-3 border-b">
			<h1 class="font-display text-xl tracking-tight">{ctx?.agent?.name ?? 'Asistan'}</h1>
			{#if ctx && ctx.agent && ctx.agent.status !== 'active'}
				<p class="text-sm text-muted-foreground">Asistanınız şu an etkin değil ({ctx.agent.status}).</p>
			{:else if ctx && !ctx.agent}
				<p class="text-sm text-muted-foreground">Size atanmış bir asistan henüz yok. Yöneticinizle konuşun.</p>
			{/if}
		</header>

		<div bind:this={scroller} class="flex-1 overflow-y-auto p-4 space-y-4" aria-live="polite">
			{#each turns as t}
				<div class={t.role === 'user' ? 'ml-auto max-w-[85%] rounded-xl bg-primary/10 px-3 py-2' : 'max-w-[90%]'}>
					{#if t.role === 'assistant'}
						<MessageContent content={t.content} />
						{#if t.sources?.length}
							<details class="mt-1 rounded-lg border p-2 text-xs">
								<summary class="cursor-pointer font-medium">Kaynaklar ({t.sources.length})</summary>
								<ol class="mt-1 list-decimal pl-4 space-y-1">
									{#each t.sources as s}<li><span class="text-muted-foreground">{s.kind} · {s.date}</span> — {s.snippet}</li>{/each}
								</ol>
							</details>
						{/if}
					{:else}<p class="whitespace-pre-wrap text-sm">{t.content}</p>{/if}
				</div>
			{/each}
			{#if streaming}
				<div class="max-w-[90%]">
					{#if streamingText}<MessageContent content={streamingText} streaming={true} />{/if}
					<p class="text-xs text-muted-foreground flex items-center gap-1 mt-1"><Loader class="w-3 h-3 animate-spin" />{status}</p>
				</div>
			{/if}
			{#if error}<p class="text-sm text-destructive" role="alert">{error}</p>{/if}
		</div>

		<footer class="border-t p-3 space-y-2">
			{#if attachments.length}
				<ul class="flex flex-wrap gap-2 text-xs">
					{#each attachments as a, i}
						<li class="inline-flex items-center gap-1 rounded-md border px-2 py-1">
							{a.filename}
							<button aria-label="Dosyayı kaldır" onclick={() => (attachments = attachments.filter((_, j) => j !== i))}><X class="w-3 h-3" /></button>
						</li>
					{/each}
				</ul>
			{/if}
			<div class="flex items-end gap-2">
				<input bind:this={fileInput} type="file" class="hidden" accept=".pdf,.txt,.md,.csv,image/*" onchange={pickFile} />
				<Button variant="outline" size="icon" aria-label="Dosya ekle" disabled={!canChat || streaming} onclick={() => fileInput?.click()}>
					<Paperclip class="w-4 h-4" />
				</Button>
				<textarea
					class="flex-1 resize-none rounded-md border bg-background p-2 text-sm min-h-[2.5rem] max-h-40"
					rows="1"
					placeholder="Bir şey sorun veya bir iş verin…"
					bind:value={draft}
					onkeydown={onKey}
					disabled={!canChat}
					aria-label="Mesaj"
				></textarea>
				<Button onclick={send} disabled={streaming || !canChat || (!draft.trim() && !attachments.length)} aria-label="Gönder">
					<Send class="w-4 h-4" />
				</Button>
			</div>
		</footer>
	</section>

	<aside class="space-y-3 overflow-y-auto text-sm" aria-label="Bağlamım">
		{#if ctx}
			<details open class="rounded-xl border p-3">
				<summary class="font-medium cursor-pointer">Ben</summary>
				<p class="mt-2">{ctx.me.name}{ctx.me.title ? ` · ${ctx.me.title}` : ''}</p>
				{#if ctx.team.department}<p class="text-muted-foreground">{ctx.team.department}</p>{/if}
				{#if ctx.team.manager}<p class="text-muted-foreground">Yönetici: {ctx.team.manager.name}{ctx.team.manager.role ? ` (${ctx.team.manager.role})` : ''}</p>{/if}
			</details>
			{#if ctx.team.colleagues.length}
				<details class="rounded-xl border p-3">
					<summary class="font-medium cursor-pointer">Çalışma arkadaşları ({ctx.team.colleagues.length})</summary>
					<ul class="mt-2 space-y-1">{#each ctx.team.colleagues as c}<li>{c.name}{c.role ? ` · ${c.role}` : ''}</li>{/each}</ul>
				</details>
			{/if}
			<details class="rounded-xl border p-3">
				<summary class="font-medium cursor-pointer">Bağlı araçlar ({ctx.tools.length})</summary>
				<ul class="mt-2 space-y-1">{#each ctx.tools as t}<li><strong>{t.name}</strong>{t.description ? ` — ${t.description}` : ''}</li>{:else}<li class="text-muted-foreground">Henüz araç yok.</li>{/each}</ul>
			</details>
			<details class="rounded-xl border p-3">
				<summary class="font-medium cursor-pointer">Politikalar ({ctx.policies.length})</summary>
				<div class="mt-2 space-y-3">{#each ctx.policies as p}<div><p class="font-medium">{p.name}</p><div class="text-muted-foreground"><MessageContent content={p.content} /></div></div>{:else}<p class="text-muted-foreground">Uygulanan politika yok.</p>{/each}</div>
			</details>
			{#if outputs}
				<details class="rounded-xl border p-3">
					<summary class="font-medium cursor-pointer">Çıktılarım ({outputs.files.length})</summary>
					<ul class="mt-2 space-y-1">
						{#each outputs.files as f}
							<li class="flex items-center justify-between gap-2">
								<span class="truncate" title={f.path}>{f.path}</span>
								<button
									class="underline text-xs"
									onclick={() => {
										if (isRisky(f.path) && !confirm('Bu dosya türü makro/komut içerebilir. Yine de kaydedilsin mi? Açmadan önce kontrol edin.')) return;
										outputsApi.download(outputs!.id, f.path).catch((e) => (error = e.message));
									}}>İndir</button>
							</li>
						{:else}<li class="text-muted-foreground">Henüz çıktı yok.</li>{/each}
					</ul>
				</details>
			{/if}
			{#if ctx.learned.length}
				<details class="rounded-xl border p-3">
					<summary class="font-medium cursor-pointer">Öğrenilmiş yönergeler ({ctx.learned.length})</summary>
					<ul class="mt-2 space-y-2">
						{#each ctx.learned as l}<li><span class="text-muted-foreground">{l.level} · v{l.version}</span><br />{l.text}</li>{/each}
					</ul>
				</details>
			{/if}
			<details class="rounded-xl border p-3">
				<summary class="font-medium cursor-pointer">Misyon, vizyon, hedefler</summary>
				<div class="mt-2 space-y-2">
					{#if ctx.company.mission}<p><strong>Misyon:</strong> {ctx.company.mission}</p>{/if}
					{#if ctx.company.vision}<p><strong>Vizyon:</strong> {ctx.company.vision}</p>{/if}
					{#if ctx.company.department_goals}<p class="whitespace-pre-line"><strong>Bölüm hedefleri:</strong> {ctx.company.department_goals}</p>{/if}
				</div>
			</details>
		{:else if error}
			<p class="text-destructive" role="alert">{error}</p>
		{:else}
			<Loader class="w-4 h-4 animate-spin" />
		{/if}
	</aside>
</div>
