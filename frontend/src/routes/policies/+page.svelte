<script lang="ts">
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import YapiTabs from '$lib/components/ui/yapi-tabs.svelte';
	import {
		Plus, X, Pencil, Trash2, FileText, Loader, Eye,
		AlertTriangle, Check, Building2, Users, Bot,
	} from '@lucide/svelte';
	import { policiesApi, type Policy, type PolicyCreate } from '$lib/api/policies';
	import { companyStore } from '$lib/stores/company.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { t } from '$lib/i18n/index.svelte';

	let allPolicies: Policy[] = $state([]);
	let scopeFilter = $state<'all' | 'company' | 'department' | 'agent'>('all');
	let loading = $state(true);
	let error: string | null = $state(null);

	async function load() {
		loading = true; error = null;
		try {
			allPolicies = await policiesApi.list({ company_id: companyStore.active?.id });
		} catch (e) { error = (e as Error).message; }
		finally { loading = false; }
	}

	onMount(load);
	$effect(() => { if (companyStore.active) load(); });

	const activeCompanyId = $derived(companyStore.active?.id ?? '');
	const canManage = $derived(authStore.can(activeCompanyId, 'dept_head'));

	const policies = $derived(
		scopeFilter === 'all' ? allPolicies : allPolicies.filter(p => p.scope === scopeFilter)
	);

	const SCOPE_LABELS = $derived<Record<string, string>>({
		company: t('policy_scope_company'), department: t('policy_scope_department'), agent: t('policy_scope_agent'),
	});
	const SCOPE_ICONS: Record<string, any> = {
		company: Building2, department: Users, agent: Bot,
	};
	const SCOPE_COLORS: Record<string, string> = {
		company: 'default', department: 'secondary', agent: 'outline',
	};

	// ── Panel state ──────────────────────────────────────────────────────────
	type PanelMode = 'view' | 'edit' | 'create';
	let panelMode = $state<PanelMode | null>(null);
	let selected = $state<Policy | null>(null);
	let editorTab = $state<'write' | 'preview'>('write');
	let saving = $state(false);
	let crSubmitted = $state(false);

	let form = $state<PolicyCreate & { content: string; is_active: boolean }>({
		company_id: '', name: '', slug: '', content: '',
		scope: 'company', department_id: '', agent_config_id: '', is_active: true,
	});

	function slugify(t: string) {
		return t.toLowerCase()
			.replace(/ğ/g,'g').replace(/ş/g,'s').replace(/ı/g,'i')
			.replace(/ö/g,'o').replace(/ü/g,'u').replace(/ç/g,'c')
			.replace(/[^a-z0-9\s-]/g,'').trim().replace(/\s+/g,'-');
	}

	$effect(() => { if (panelMode === 'create') form.slug = slugify(form.name); });

	function openView(p: Policy) {
		selected = p; panelMode = 'view'; editorTab = 'write'; crSubmitted = false;
	}
	function openEdit(p: Policy) {
		selected = p;
		form = {
			company_id: p.company_id, name: p.name, slug: p.slug,
			content: p.content ?? '', scope: p.scope,
			department_id: p.department_id ?? '',
			agent_config_id: p.agent_config_id ?? '',
			is_active: p.is_active,
		};
		editorTab = 'write'; crSubmitted = false;
		panelMode = 'edit';
	}
	function openCreate() {
		selected = null;
		form = {
			company_id: companyStore.active?.id ?? '', name: '', slug: '',
			content: DEFAULT_CONTENT, scope: 'company',
			department_id: '', agent_config_id: '', is_active: true,
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
				const body: PolicyCreate = {
					company_id: form.company_id || companyStore.active?.id || '',
					name: form.name, slug: form.slug,
					content: form.content || undefined,
					scope: form.scope,
					department_id: form.department_id || undefined,
					agent_config_id: form.agent_config_id || undefined,
				};
				const created = await policiesApi.create(body);
				allPolicies = [...allPolicies, created as Policy];
				closePanel();
			} else if (panelMode === 'edit' && selected) {
				const res = await policiesApi.update(selected.id, {
					name: form.name, slug: form.slug,
					content: form.content,
					scope: form.scope,
					department_id: form.department_id || undefined,
					agent_config_id: form.agent_config_id || undefined,
					is_active: form.is_active,
				}, true, authStore.user?.id);
				if ('change_request_id' in (res as any)) {
					crSubmitted = true;
				} else {
					allPolicies = allPolicies.map(p => p.id === selected!.id ? res as Policy : p);
					openView(res as Policy);
				}
			}
		} catch (e) { alert((e as Error).message); }
		finally { saving = false; }
	}

	async function deletePolicy(p: Policy) {
		if (!confirm(`"${p.name}" politikasını silmek istediğinize emin misiniz?`)) return;
		try {
			await policiesApi.delete(p.id);
			allPolicies = allPolicies.filter(x => x.id !== p.id);
			if (selected?.id === p.id) closePanel();
		} catch (e) { alert((e as Error).message); }
	}

	const preview = $derived(form.content ? marked(form.content) as string : '');
	const selectedPreview = $derived(selected?.content ? marked(selected.content) as string : '');

	const DEFAULT_CONTENT = `## Politika Tanımı

Bu politikanın amacı ve kapsamını buraya yaz.

## Kurallar

1. Kural birinci
2. Kural ikinci

## İstisnalar

- İstisna durumlar

## Yürürlük

Bu politika onay tarihinden itibaren geçerlidir.
`;
</script>

<svelte:head>
	<title>{t('policy_title')} • fab.engineering</title>
</svelte:head>

<div class="space-y-6">
	<YapiTabs />

	<div class="flex items-center justify-between gap-4 flex-wrap">
		<div>
			<h1 class="font-display text-3xl tracking-tight">{t('policy_title')}</h1>
			<p class="text-muted-foreground mt-1">{t('policy_subtitle')} · {allPolicies.length} {t('policy_count_suffix')}</p>
		</div>
		{#if canManage}
			<Button onclick={openCreate} class="gap-2">
				<Plus class="w-4 h-4" /> {t('policy_new')}
			</Button>
		{/if}
	</div>

	<!-- Scope filter pills -->
	<div class="flex gap-2 flex-wrap">
		{#each [['all', t('filter')], ['company', t('policy_scope_company')], ['department', t('policy_scope_department')], ['agent', t('policy_scope_agent')]] as [val, lbl]}
			<button
				class="scope-pill {scopeFilter === val ? 'scope-pill-active' : 'scope-pill-inactive'}"
				onclick={() => (scopeFilter = val as any)}
			>{lbl}</button>
		{/each}
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-20 text-muted-foreground gap-2">
			<Loader class="w-5 h-5 animate-spin" /><span class="text-sm">{t('loading')}</span>
		</div>
	{:else if error}
		<div class="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">{error}</div>
	{:else if policies.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
				<FileText class="w-6 h-6 text-muted-foreground" />
			</div>
			<div>
				<p class="font-medium">{t('policy_empty')}</p>
				<p class="text-sm text-muted-foreground mt-1">{t('policy_empty_desc')}</p>
			</div>
			{#if canManage}
				<Button onclick={openCreate} size="sm" class="gap-2 mt-2">
					<Plus class="w-4 h-4" /> {t('policy_new')}
				</Button>
			{/if}
		</div>
	{:else}
		<div class="space-y-2">
			{#each policies as p (p.id)}
				{@const Icon = SCOPE_ICONS[p.scope] ?? FileText}
				<button
					class="policy-row {selected?.id === p.id ? 'policy-row-active' : ''}"
					onclick={() => openView(p)}
				>
					<div class="flex items-center gap-3 min-w-0">
						<div class="w-8 h-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
							<Icon class="w-4 h-4 text-muted-foreground" />
						</div>
						<div class="min-w-0">
							<div class="font-medium text-sm truncate">{p.name}</div>
							<div class="text-xs text-muted-foreground font-mono">{p.slug}</div>
						</div>
					</div>
					<div class="flex items-center gap-2 flex-shrink-0">
						{#if p.scope !== 'company' && !p.is_active}
							<span class="text-xs text-amber-600">Pasif</span>
						{/if}
						<Badge variant={SCOPE_COLORS[p.scope] as any}>{SCOPE_LABELS[p.scope]}</Badge>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>

<!-- ── Side Panel ────────────────────────────────────────────────────────── -->
{#if panelMode !== null}
	<div class="fixed inset-0 z-30 bg-black/30 lg:hidden" onclick={closePanel} aria-hidden="true"></div>

	<aside class="policy-panel">
		<!-- Header -->
		<div class="flex items-center justify-between px-5 py-4 border-b flex-shrink-0">
			{#if panelMode === 'view' && selected}
				{@const Icon = SCOPE_ICONS[selected.scope] ?? FileText}
				<div class="flex items-center gap-3 min-w-0">
					<div class="w-9 h-9 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
						<Icon class="w-4 h-4 text-muted-foreground" />
					</div>
					<div class="min-w-0">
						<div class="font-semibold truncate">{selected.name}</div>
						<Badge variant={SCOPE_COLORS[selected.scope] as any} class="text-xs mt-0.5">
							{SCOPE_LABELS[selected.scope]}
						</Badge>
					</div>
				</div>
			{:else}
				<span class="font-semibold">{panelMode === 'edit' ? t('policy_panel_edit') : t('policy_new')}</span>
			{/if}
			<button class="text-muted-foreground hover:text-foreground ml-2 flex-shrink-0" onclick={closePanel}>
				<X class="w-5 h-5" />
			</button>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-y-auto">

			<!-- VIEW -->
			{#if panelMode === 'view' && selected}
				<div class="p-5 space-y-4">
					{#if selected.content}
						<div class="rounded-xl border border-border bg-muted/20 p-4">
							<div class="prose-sm" style="font-size:0.8125rem;line-height:1.7">
								{@html selectedPreview}
							</div>
						</div>
					{:else}
						<div class="rounded-xl border border-dashed border-border py-8 flex items-center justify-center text-sm text-muted-foreground">
							{t('policy_no_content')}
						</div>
					{/if}

					<div class="text-xs text-muted-foreground space-y-1">
						<div>Slug: <span class="font-mono">{selected.slug}</span></div>
						{#if selected.scope === 'company'}
							<div class="flex items-center gap-1.5 text-emerald-700">
								<Check class="w-3 h-3" />
								{t('policy_active')} — always on
							</div>
						{:else}
							<div>{t('status')}: <span class="{selected.is_active ? 'text-emerald-600' : 'text-amber-600'}">{selected.is_active ? t('policy_active') : t('policy_inactive')}</span></div>
						{/if}
					</div>
				</div>

			<!-- EDIT / CREATE -->
			{:else if panelMode === 'edit' || panelMode === 'create'}
				{#if crSubmitted}
					<div class="p-5 flex flex-col items-center justify-center gap-4 py-20 text-center">
						<div class="w-12 h-12 rounded-full bg-emerald-100 flex items-center justify-center">
							<Check class="w-6 h-6 text-emerald-600" />
						</div>
						<div>
							<div class="font-semibold">{t('policy_cr_title')}</div>
							<div class="text-sm text-muted-foreground mt-1">{t('policy_cr_desc')}</div>
						</div>
						<Button variant="outline" onclick={() => { crSubmitted = false; selected && openView(selected); }}>
							Kapat
						</Button>
					</div>
				{:else}
					<div class="p-5 space-y-4">
						{#if panelMode === 'edit'}
							<div class="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
								<AlertTriangle class="w-3.5 h-3.5 flex-shrink-0" />
								{t('policy_edit_warning')}
							</div>
						{/if}

						<div class="grid grid-cols-2 gap-3">
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="pol-name">{t('policy_form_name')}</label>
								<Input id="pol-name" bind:value={form.name} placeholder="Data Security" />
							</div>
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="pol-slug">{t('policy_form_slug')}</label>
								<Input id="pol-slug" bind:value={form.slug} placeholder="veri-guvenligi" class="font-mono text-xs" />
							</div>
						</div>

						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="pol-scope">{t('policy_form_scope')}</label>
							<select id="pol-scope" class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm" bind:value={form.scope}>
								<option value="company">{t('policy_scope_company')}</option>
								<option value="department">{t('policy_scope_department')}</option>
								<option value="agent">{t('policy_scope_agent')}</option>
							</select>
						</div>

						{#if form.scope === 'department'}
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="pol-dept">{t('policy_form_dept')} ID</label>
								<Input id="pol-dept" bind:value={form.department_id} placeholder="uuid" class="font-mono text-xs" />
							</div>
						{:else if form.scope === 'agent'}
							<div class="space-y-1.5">
								<label class="text-sm font-medium" for="pol-agent">Ajan Config ID</label>
								<Input id="pol-agent" bind:value={form.agent_config_id} placeholder="uuid" class="font-mono text-xs" />
							</div>
						{/if}

						{#if form.scope === 'company'}
							<div class="flex items-center gap-2 rounded-lg bg-muted/50 border border-border px-3 py-2 text-xs text-muted-foreground">
								<Check class="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
								Şirket politikaları her zaman aktiftir, pasif edilemez.
							</div>
						{:else}
							<div class="space-y-1.5">
								<label class="flex items-center gap-2 text-sm cursor-pointer">
									<input type="checkbox" bind:checked={form.is_active} class="rounded" />
									Aktif
								</label>
							</div>
						{/if}

						<!-- Markdown Editor -->
						<div class="space-y-1.5">
							<div class="flex items-center justify-between">
								<label class="text-sm font-medium">{t('policy_form_content')}</label>
								<div class="flex gap-1">
									<button
										class="text-xs px-2 py-1 rounded {editorTab === 'write' ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground'}"
										onclick={() => (editorTab = 'write')}>
										<Pencil class="w-3 h-3 inline mr-1" />{t('policy_write_tab')}
									</button>
									<button
										class="text-xs px-2 py-1 rounded {editorTab === 'preview' ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground'}"
										onclick={() => (editorTab = 'preview')}>
										<Eye class="w-3 h-3 inline mr-1" />{t('policy_preview_tab')}
									</button>
								</div>
							</div>
							{#if editorTab === 'write'}
								<textarea
									bind:value={form.content}
									class="md-editor"
									rows="18"
									placeholder="## Politika Başlığı&#10;&#10;Bu politikanın amacı..."
								></textarea>
							{:else}
								<div class="md-preview">
									{#if form.content}
										<div class="prose-sm" style="font-size:0.8125rem;line-height:1.7">
											{@html preview}
										</div>
									{:else}
										<p class="text-muted-foreground text-sm">{t('policy_no_preview')}</p>
									{/if}
								</div>
							{/if}
						</div>
					</div>
				{/if}
			{/if}
		</div>

		<!-- Footer -->
		{#if panelMode === 'view' && canManage && !crSubmitted}
			<div class="flex gap-2 p-4 border-t flex-shrink-0">
				<Button variant="outline" size="sm" class="flex-1 gap-1.5" onclick={() => selected && openEdit(selected)}>
					<Pencil class="w-3.5 h-3.5" /> Düzenle
				</Button>
				<Button variant="ghost" size="sm" class="text-destructive hover:bg-destructive/10"
					onclick={() => selected && deletePolicy(selected)}>
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
					{panelMode === 'edit' ? t('policy_submit_btn') : t('create')}
				</Button>
			</div>
		{/if}
	</aside>
{/if}

<style>
.scope-pill {
	padding: 0.25rem 0.75rem;
	border-radius: 999px;
	font-size: 0.8125rem;
	font-weight: 500;
	border: 1px solid transparent;
	cursor: pointer;
	transition: background 0.12s, border-color 0.12s, color 0.12s;
}
.scope-pill-active {
	background: hsl(var(--foreground));
	color: hsl(var(--background));
}
.scope-pill-inactive {
	background: hsl(var(--muted));
	color: hsl(var(--muted-foreground));
}
.scope-pill-inactive:hover {
	background: hsl(var(--muted) / 0.8);
	color: hsl(var(--foreground));
}
.policy-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 1rem;
	background: hsl(var(--card));
	border: 1px solid hsl(var(--border));
	border-radius: 0.75rem;
	padding: 0.75rem 1rem;
	cursor: pointer;
	width: 100%;
	text-align: left;
	transition: border-color 0.15s, box-shadow 0.15s;
}
.policy-row:hover {
	border-color: hsl(var(--primary) / 0.4);
	box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}
.policy-row-active {
	border-color: hsl(var(--primary));
	box-shadow: 0 0 0 1px hsl(var(--primary));
}
.policy-panel {
	position: fixed;
	top: 0; right: 0; bottom: 0;
	width: 580px;
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
	min-height: 300px;
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
	min-height: 300px;
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
:global(.prose-sm ol) { list-style-type: decimal; }
</style>
