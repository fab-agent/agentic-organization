<script lang="ts">
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import YapiTabs from '$lib/components/ui/yapi-tabs.svelte';
	import {
		Plus, X, Pencil, Trash2, Zap, Loader, Eye, Code2,
		ChevronRight, AlertTriangle, Check,
	} from '@lucide/svelte';
	import { skillsApi, type CompanySkill, type SkillCreate } from '$lib/api/skills';
	import { companyStore } from '$lib/stores/company.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { t } from '$lib/i18n/index.svelte';

	let skills: CompanySkill[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);

	async function load() {
		loading = true; error = null;
		try {
			skills = await skillsApi.list(companyStore.active?.id);
		} catch (e) { error = (e as Error).message; }
		finally { loading = false; }
	}

	onMount(load);
	$effect(() => { if (companyStore.active) load(); });

	const activeCompanyId = $derived(companyStore.active?.id ?? '');
	const canManage = $derived(authStore.can(activeCompanyId, 'dept_head'));

	// ── Skill type labels ────────────────────────────────────────────────────
	const TYPE_LABELS = $derived<Record<string, string>>({
		builtin: t('skill_type_builtin'), mcp: 'MCP', http: 'HTTP API',
		function: t('skill_type_function'), database: t('skill_type_database'),
	});
	const TYPE_COLORS: Record<string, string> = {
		builtin: 'default', mcp: 'secondary', http: 'outline',
		function: 'secondary', database: 'outline',
	};

	// ── Panel state: null | 'view' | 'edit' | 'create' ─────────────────────
	type PanelMode = 'view' | 'edit' | 'create';
	let panelMode = $state<PanelMode | null>(null);
	let selected = $state<CompanySkill | null>(null);
	let editorTab = $state<'write' | 'preview'>('write');
	let saving = $state(false);
	let crSubmitted = $state(false);

	let form = $state<SkillCreate & { content: string; is_active: boolean }>({
		company_id: '', name: '', slug: '', description: '',
		content: '', skill_type: 'builtin', config_json: '', is_active: true,
	});

	function slugify(t: string) {
		return t.toLowerCase()
			.replace(/ğ/g,'g').replace(/ş/g,'s').replace(/ı/g,'i')
			.replace(/ö/g,'o').replace(/ü/g,'u').replace(/ç/g,'c')
			.replace(/[^a-z0-9\s-]/g,'').trim().replace(/\s+/g,'-');
	}

	$effect(() => { if (panelMode === 'create') form.slug = slugify(form.name); });

	function openView(s: CompanySkill) {
		selected = s; panelMode = 'view'; editorTab = 'write'; crSubmitted = false;
	}
	function openEdit(s: CompanySkill) {
		selected = s;
		form = {
			company_id: s.company_id, name: s.name, slug: s.slug,
			description: s.description ?? '', content: s.content ?? '',
			skill_type: s.skill_type, config_json: s.config_json ?? '',
			is_active: s.is_active,
		};
		editorTab = 'write'; crSubmitted = false;
		panelMode = 'edit';
	}
	function openCreate() {
		selected = null;
		form = {
			company_id: companyStore.active?.id ?? '', name: '', slug: '',
			description: '', content: DEFAULT_CONTENT, skill_type: 'builtin',
			config_json: '', is_active: true,
		};
		editorTab = 'write'; crSubmitted = false;
		panelMode = 'create';
	}
	function closePanel() { panelMode = null; selected = null; }

	async function save() {
		if (!form.name.trim()) return;
		saving = true;
		try {
			if (panelMode === 'create') {
				const created = await skillsApi.create({
					company_id: form.company_id || companyStore.active?.id || '',
					name: form.name, slug: form.slug,
					description: form.description || undefined,
					content: form.content || undefined,
					skill_type: form.skill_type,
					config_json: form.config_json || undefined,
				});
				skills = [...skills, created as CompanySkill];
				closePanel();
			} else if (panelMode === 'edit' && selected) {
				// Propose as CR — content changes must be approved
				const res = await skillsApi.update(selected.id, {
					name: form.name, slug: form.slug,
					description: form.description || undefined,
					content: form.content,
					skill_type: form.skill_type,
					config_json: form.config_json || undefined,
					is_active: form.is_active,
				}, true, authStore.user?.id);
				if ('change_request_id' in (res as any)) {
					crSubmitted = true;
				} else {
					skills = skills.map(s => s.id === selected!.id ? res as CompanySkill : s);
					openView(res as CompanySkill);
				}
			}
		} catch (e) { alert((e as Error).message); }
		finally { saving = false; }
	}

	async function deleteSkill(s: CompanySkill) {
		if (!confirm(`"${s.name}" yeteneğini silmek istediğinize emin misiniz?`)) return;
		try {
			await skillsApi.delete(s.id);
			skills = skills.filter(x => x.id !== s.id);
			if (selected?.id === s.id) closePanel();
		} catch (e) { alert((e as Error).message); }
	}

	const preview = $derived(form.content ? marked(form.content) as string : '');
	const selectedPreview = $derived(selected?.content ? marked(selected.content) as string : '');

	const DEFAULT_CONTENT = `## Açıklama

Bu yeteneğin ne yaptığını buraya yaz.

## Kullanım

\`\`\`
örnek kullanım
\`\`\`

## Parametreler

| Parametre | Tip | Açıklama |
|-----------|-----|----------|
| - | - | - |

## Notlar

- Önemli kısıtlamalar
- Bağımlılıklar
`;
</script>

<svelte:head>
	<title>{t('skill_title')} • fab.engineering</title>
</svelte:head>

<div class="space-y-6">
	<YapiTabs />

	<div class="flex items-center justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">{t('skill_title')}</h1>
			<p class="text-muted-foreground mt-1">{t('skill_subtitle')} · {skills.length} {t('skill_count_suffix')}</p>
		</div>
		{#if canManage}
			<Button onclick={openCreate} class="gap-2">
				<Plus class="w-4 h-4" /> {t('skill_new')}
			</Button>
		{/if}
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-20 text-muted-foreground gap-2">
			<Loader class="w-5 h-5 animate-spin" /><span class="text-sm">{t('loading')}</span>
		</div>
	{:else if error}
		<div class="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">{error}</div>
	{:else if skills.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
				<Zap class="w-6 h-6 text-muted-foreground" />
			</div>
			<div>
				<p class="font-medium">{t('skill_empty')}</p>
				<p class="text-sm text-muted-foreground mt-1">{t('skill_empty_desc')}</p>
			</div>
			{#if canManage}
				<Button onclick={openCreate} size="sm" class="gap-2 mt-2">
					<Plus class="w-4 h-4" /> {t('skill_new')}
				</Button>
			{/if}
		</div>
	{:else}
		<div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
			{#each skills as s (s.id)}
				<button
					class="skill-card text-left {selected?.id === s.id ? 'ring-1 ring-primary' : ''}"
					onclick={() => openView(s)}
				>
					<div class="flex items-start justify-between gap-2 mb-2">
						<div class="flex items-center gap-2 min-w-0">
							<div class="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
								<Zap class="w-4 h-4 text-primary" />
							</div>
							<div class="min-w-0">
								<div class="font-semibold text-sm truncate">{s.name}</div>
								<div class="text-xs text-muted-foreground font-mono">{s.slug}</div>
							</div>
						</div>
						<Badge variant={TYPE_COLORS[s.skill_type] as any}>{TYPE_LABELS[s.skill_type]}</Badge>
					</div>
					{#if s.description}
						<p class="text-xs text-muted-foreground leading-relaxed line-clamp-2">{s.description}</p>
					{/if}
					<div class="flex items-center justify-between mt-3">
						<span class="text-xs text-muted-foreground">
							{s.assigned_agents.length} {t('skill_assigned')}
						</span>
						<ChevronRight class="w-3.5 h-3.5 text-muted-foreground" />
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>

<!-- ── Side Panel ────────────────────────────────────────────────────────── -->
{#if panelMode !== null}
	<div class="fixed inset-0 z-30 bg-black/30 lg:hidden" onclick={closePanel} aria-hidden="true"></div>

	<aside class="skill-panel">
		<!-- Header -->
		<div class="flex items-center justify-between px-5 py-4 border-b flex-shrink-0">
			{#if panelMode === 'view'}
				<div class="flex items-center gap-3 min-w-0">
					<div class="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
						<Zap class="w-4 h-4 text-primary" />
					</div>
					<div class="min-w-0">
						<div class="font-semibold truncate">{selected?.name}</div>
						<Badge variant={TYPE_COLORS[selected?.skill_type ?? 'builtin'] as any} class="text-xs mt-0.5">
							{TYPE_LABELS[selected?.skill_type ?? 'builtin']}
						</Badge>
					</div>
				</div>
			{:else}
				<span class="font-semibold">{panelMode === 'edit' ? t('skill_panel_edit') : t('skill_new')}</span>
			{/if}
			<button class="text-muted-foreground hover:text-foreground ml-2 flex-shrink-0" onclick={closePanel}>
				<X class="w-5 h-5" />
			</button>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-y-auto">

			<!-- VIEW MODE -->
			{#if panelMode === 'view' && selected}
				<div class="p-5 space-y-5">
					{#if selected.description}
						<p class="text-sm text-muted-foreground">{selected.description}</p>
					{/if}

					<div class="flex items-center gap-4 text-xs text-muted-foreground">
						<span>{selected.assigned_agents.length} {t('skill_assigned')}</span>
						{#if !selected.is_active}
							<span class="text-amber-600 font-medium">{t('skill_inactive')}</span>
						{/if}
					</div>

					{#if selected.content}
						<div class="rounded-xl border border-border bg-muted/20 p-4">
							<div class="prose-sm" style="font-size:0.8125rem;line-height:1.7">
								{@html selectedPreview}
							</div>
						</div>
					{:else}
						<div class="rounded-xl border border-dashed border-border py-8 flex items-center justify-center text-sm text-muted-foreground">
							{t('skill_no_content')}
						</div>
					{/if}

					{#if selected.config_json}
						<div>
							<div class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
								<Code2 class="w-3.5 h-3.5" /> {t('skill_config_label')}
							</div>
							<pre class="text-xs bg-muted/50 rounded-lg p-3 overflow-x-auto">{JSON.stringify(JSON.parse(selected.config_json), null, 2)}</pre>
						</div>
					{/if}
				</div>

			<!-- EDIT / CREATE MODE -->
			{:else if panelMode === 'edit' || panelMode === 'create'}
				{#if crSubmitted}
					<div class="p-5 flex flex-col items-center justify-center gap-4 py-20 text-center">
						<div class="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center">
							<Check class="w-6 h-6 text-emerald-600" />
						</div>
						<div>
							<div class="font-semibold">{t('skill_cr_title')}</div>
							<div class="text-sm text-muted-foreground mt-1">{t('skill_cr_desc')}</div>
						</div>
						<Button variant="outline" onclick={() => { crSubmitted = false; selected && openView(selected); }}>
							{t('close')}
						</Button>
					</div>
				{:else}
					<div class="p-5 space-y-4">
						{#if panelMode === 'edit'}
							<div class="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
								<AlertTriangle class="w-3.5 h-3.5 flex-shrink-0" />
								{t('skill_edit_warning')}
							</div>
						{/if}

						<div class="grid grid-cols-2 gap-3">
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="sk-name">{t('skill_form_name')}</label>
								<Input id="sk-name" bind:value={form.name} placeholder={t('skill_name_ph')} />
							</div>
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="sk-slug">{t('skill_form_slug')}</label>
								<Input id="sk-slug" bind:value={form.slug} placeholder={t('skill_slug_ph')} class="font-mono text-xs" />
							</div>
						</div>

						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="sk-desc">{t('skill_form_desc')}</label>
							<Input id="sk-desc" bind:value={form.description} placeholder={t('skill_desc_ph')} />
						</div>

						<div class="grid grid-cols-2 gap-3">
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="sk-type">{t('skill_form_type')}</label>
								<select id="sk-type" class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm" bind:value={form.skill_type}>
									{#each Object.entries(TYPE_LABELS) as [val, lbl]}
										<option value={val}>{lbl}</option>
									{/each}
								</select>
							</div>
							<div class="space-y-1.5 flex items-end">
								<label class="flex items-center gap-2 text-sm cursor-pointer">
									<input type="checkbox" bind:checked={form.is_active} class="rounded" />
									{t('skill_form_active')}
								</label>
							</div>
						</div>

						<!-- Markdown Editor -->
						<div class="space-y-1.5">
							<div class="flex items-center justify-between">
								<label class="text-sm font-medium">{t('skill_form_content')}</label>
								<div class="flex gap-1">
									<button
										class="text-xs px-2 py-1 rounded {editorTab === 'write' ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground'}"
										onclick={() => (editorTab = 'write')}>
										<Pencil class="w-3 h-3 inline mr-1" />{t('skill_write_tab')}
									</button>
									<button
										class="text-xs px-2 py-1 rounded {editorTab === 'preview' ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground'}"
										onclick={() => (editorTab = 'preview')}>
										<Eye class="w-3 h-3 inline mr-1" />{t('skill_preview_tab')}
									</button>
								</div>
							</div>
							{#if editorTab === 'write'}
								<textarea
									bind:value={form.content}
									class="md-editor"
									rows="16"
									placeholder={t('skill_content_ph')}
								></textarea>
							{:else}
								<div class="md-preview">
									{#if form.content}
										<div class="prose-sm" style="font-size:0.8125rem;line-height:1.7">
											{@html preview}
										</div>
									{:else}
										<p class="text-muted-foreground text-sm">{t('skill_no_preview')}</p>
									{/if}
								</div>
							{/if}
						</div>

						{#if form.skill_type !== 'builtin'}
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="sk-config">{t('skill_config_json')}</label>
								<textarea
									id="sk-config"
									bind:value={form.config_json}
									class="md-editor font-mono text-xs"
									rows="5"
									placeholder='{`{"url": "https://...", "auth": "..."}`}'
								></textarea>
							</div>
						{/if}
					</div>
				{/if}
			{/if}
		</div>

		<!-- Footer -->
		{#if panelMode === 'view' && canManage && !crSubmitted}
			<div class="flex gap-2 p-4 border-t flex-shrink-0">
				<Button variant="outline" size="sm" class="flex-1 gap-1.5" onclick={() => selected && openEdit(selected)}>
					<Pencil class="w-3.5 h-3.5" /> {t('skill_edit_btn')}
				</Button>
				<Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10"
					onclick={() => selected && deleteSkill(selected)}>
					<Trash2 class="w-3.5 h-3.5" />
				</Button>
			</div>
		{:else if (panelMode === 'edit' || panelMode === 'create') && !crSubmitted}
			<div class="flex gap-2 p-4 border-t flex-shrink-0">
				<Button variant="outline" class="flex-1"
					onclick={() => panelMode === 'edit' && selected ? openView(selected) : closePanel()}>
					{t('cancel')}
				</Button>
				<Button class="flex-1" onclick={save} disabled={!form.name.trim() || saving}>
					{#if saving}
						<Loader class="w-4 h-4 animate-spin mr-1" />
					{/if}
					{panelMode === 'edit' ? t('skill_submit_btn') : t('create')}
				</Button>
			</div>
		{/if}
	</aside>
{/if}

<style>
.skill-card {
	background: hsl(var(--card));
	border: 1px solid hsl(var(--border));
	border-radius: 0.75rem;
	padding: 1rem;
	cursor: pointer;
	transition: border-color 0.15s, box-shadow 0.15s;
	display: block;
	width: 100%;
}
.skill-card:hover {
	border-color: hsl(var(--primary) / 0.4);
	box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.skill-panel {
	position: fixed;
	top: 0; right: 0; bottom: 0;
	width: 560px;
	max-width: 100vw;
	background: hsl(var(--card));
	border-left: 1px solid hsl(var(--border));
	box-shadow: -8px 0 32px rgba(0,0,0,0.08);
	z-index: 40;
	display: flex;
	flex-direction: column;
	animation: slideIn 0.18s cubic-bezier(0.32,0.72,0,1);
}
@keyframes slideIn { from { transform: translateX(100%); } to { transform: translateX(0); } }
.md-editor {
	width: 100%;
	min-height: 280px;
	border-radius: 0.375rem;
	border: 1px solid hsl(var(--input));
	background: hsl(var(--background));
	padding: 0.75rem;
	font-size: 0.8125rem;
	line-height: 1.6;
	font-family: 'JetBrains Mono', 'Fira Mono', monospace;
	resize: vertical;
	outline: none;
}
.md-editor:focus { box-shadow: 0 0 0 1px hsl(var(--ring)); }
.md-preview {
	min-height: 280px;
	border-radius: 0.375rem;
	border: 1px solid hsl(var(--border));
	background: hsl(var(--muted) / 0.3);
	padding: 0.75rem 1rem;
}
:global(.prose-sm h1) { font-size: 1.1rem; font-weight: 700; margin: 0.75rem 0 0.4rem; }
:global(.prose-sm h2) { font-size: 0.95rem; font-weight: 600; margin: 0.75rem 0 0.3rem; color: hsl(var(--foreground)); }
:global(.prose-sm h3) { font-size: 0.875rem; font-weight: 600; margin: 0.5rem 0 0.25rem; }
:global(.prose-sm p)  { margin: 0.3rem 0; color: hsl(var(--muted-foreground)); }
:global(.prose-sm ul, .prose-sm ol) { padding-left: 1.25rem; margin: 0.3rem 0; color: hsl(var(--muted-foreground)); }
:global(.prose-sm li) { margin: 0.15rem 0; }
:global(.prose-sm code) { font-family: monospace; background: hsl(var(--muted)); padding: 0.1em 0.3em; border-radius: 0.25rem; font-size: 0.8em; }
:global(.prose-sm pre) { background: hsl(var(--muted)); border-radius: 0.5rem; padding: 0.75rem; overflow-x: auto; margin: 0.5rem 0; }
:global(.prose-sm pre code) { background: none; padding: 0; }
:global(.prose-sm table) { width: 100%; border-collapse: collapse; font-size: 0.8rem; margin: 0.5rem 0; }
:global(.prose-sm th, .prose-sm td) { border: 1px solid hsl(var(--border)); padding: 0.25rem 0.5rem; text-align: left; }
:global(.prose-sm th) { background: hsl(var(--muted)/0.5); font-weight: 600; }
</style>
