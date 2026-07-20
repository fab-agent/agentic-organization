<script lang="ts">
	import { onMount } from 'svelte';
	import OrgChartNode from '$lib/components/OrgChartNode.svelte';
	import AgentDetailPanel from '$lib/components/AgentDetailPanel.svelte';
	import type { OrgNode } from '$lib/types/org';
	import { orgTree } from '$lib/api/orgtree';
	import { departments as deptApi, type Department } from '$lib/api/departments';
	import { personnel as personnelApi } from '$lib/api/personnel';
	import { companyStore } from '$lib/stores/company.svelte';
	import { Building2, Users, ChevronRight, ChevronDown } from '@lucide/svelte';
	import { t } from '$lib/i18n/index.svelte';

	// ── Data ──────────────────────────────────────────────────────────────────
	let roots: OrgNode[] = $state([]);
	let loading = $state(true);
	let loadError: string | null = $state(null);

	// If API returns multiple roots wrap them in a synthetic node
	const tree: OrgNode = $derived(
		roots.length === 1
			? roots[0]
			: { id: '__root__', name: companyStore.active?.name ?? t('company_fallback'), title: '', type: 'human', department: null, children: roots }
	);

	// ── Department view data ──────────────────────────────────────────────────
	let deptRoots: Department[] = $state([]);
	let deptPersonnelMap: Record<string, { humans: number; agents: number }> = $state({});
	let deptLoading = $state(false);
	let expandedDepts: Set<string> = $state(new Set());

	async function load() {
		loading = true;
		loadError = null;
		try {
			roots = await orgTree.get(companyStore.active?.id);
		} catch (e) {
			loadError = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	async function loadDeptView() {
		if (!companyStore.active?.id) return;
		deptLoading = true;
		try {
			const [tree, people] = await Promise.all([
				deptApi.tree(companyStore.active.id),
				personnelApi.list({ company_id: companyStore.active.id }),
			]);
			deptRoots = tree;

			// Count personnel per department (including nested)
			const map: Record<string, { humans: number; agents: number }> = {};
			for (const p of people) {
				if (!p.department_id) continue;
				if (!map[p.department_id]) map[p.department_id] = { humans: 0, agents: 0 };
				if (p.type === 'agent') map[p.department_id].agents++;
				else map[p.department_id].humans++;
			}
			deptPersonnelMap = map;

			// Auto-expand top-level departments
			expandedDepts = new Set(tree.map(d => d.id));
		} finally {
			deptLoading = false;
		}
	}

	onMount(load);

	$effect(() => {
		if (companyStore.active) load();
	});

	// ── View mode ─────────────────────────────────────────────────────────────
	let viewMode = $state<'personnel' | 'department'>('personnel');

	$effect(() => {
		if (viewMode === 'department') loadDeptView();
	});

	function toggleDept(id: string) {
		const next = new Set(expandedDepts);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expandedDepts = next;
	}

	// ── Selection ─────────────────────────────────────────────────────────────
	let selectedAgent: OrgNode | null = $state(null);

	function handleSelect(node: OrgNode) {
		selectedAgent = selectedAgent?.id === node.id ? null : node;
	}

	function handleClose() {
		selectedAgent = null;
	}

	// ── Zoom ──────────────────────────────────────────────────────────────────
	const ZOOM_STEP = 0.1;
	const ZOOM_MIN  = 0.4;
	const ZOOM_MAX  = 1.5;

	let zoom = $state(1);

	const zoomPct = $derived(Math.round(zoom * 100) + '%');

	function zoomIn()    { zoom = Math.min(ZOOM_MAX, parseFloat((zoom + ZOOM_STEP).toFixed(2))); }
	function zoomOut()   { zoom = Math.max(ZOOM_MIN, parseFloat((zoom - ZOOM_STEP).toFixed(2))); }
	function zoomReset() { zoom = 1; }

	function handleWheel(e: WheelEvent) {
		if (!e.ctrlKey && !e.metaKey) return;
		e.preventDefault();
		if (e.deltaY < 0) zoomIn();
		else zoomOut();
	}

	// ── Stats ─────────────────────────────────────────────────────────────────
	function countNodes(node: OrgNode, type?: 'human' | 'agent'): number {
		let count = !type || node.type === type ? 1 : 0;
		for (const child of node.children ?? []) count += countNodes(child, type);
		return count;
	}

	const totalHumans = $derived(roots.reduce((s, r) => s + countNodes(r, 'human'), 0));
	const totalAgents = $derived(roots.reduce((s, r) => s + countNodes(r, 'agent'), 0));
	const activeAgents = $derived(
		roots.reduce((s, r) => {
			function count(n: OrgNode): number {
				let c = n.type === 'agent' && n.agentStatus === 'active' ? 1 : 0;
				for (const ch of n.children ?? []) c += count(ch);
				return c;
			}
			return s + count(r);
		}, 0)
	);

	function deptTotal(dept: Department): { humans: number; agents: number } {
		const direct = deptPersonnelMap[dept.id] ?? { humans: 0, agents: 0 };
		let humans = direct.humans;
		let agents = direct.agents;
		for (const child of dept.children ?? []) {
			const sub = deptTotal(child);
			humans += sub.humans;
			agents += sub.agents;
		}
		return { humans, agents };
	}
</script>

<svelte:head>
	<title>{t('org_chart_title')} • fab.engineering</title>
</svelte:head>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">{t('org_chart_title')}</h1>
			<p class="text-muted-foreground mt-1">{t('org_chart_subtitle')}</p>
		</div>

		<!-- Legend -->
		{#if !loading && roots.length > 0 && viewMode === 'personnel'}
			<div class="flex items-center gap-4 text-sm">
				<div class="flex items-center gap-2">
					<div class="w-3 h-3 rounded bg-blue-200 border border-blue-400"></div>
					<span class="text-muted-foreground">{totalHumans} {t('org_human_label')}</span>
				</div>
				<div class="flex items-center gap-2">
					<div class="w-3 h-3 rounded bg-violet-200 border border-violet-400"></div>
					<span class="text-muted-foreground">{totalAgents} {t('org_agent_label')} <span class="text-emerald-600">({activeAgents} {t('org_active_label')})</span></span>
				</div>
			</div>
		{/if}
	</div>

	<!-- View Toggle + Toolbar -->
	<div class="flex items-center justify-between gap-4">
		<!-- View mode tabs -->
		<div class="flex items-center gap-1 rounded-xl border bg-card p-1">
			<button
				onclick={() => (viewMode = 'personnel')}
				class={['flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors', viewMode === 'personnel' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'].join(' ')}
			>
				<Users class="w-3.5 h-3.5" />
				{t('org_view_personnel')}
			</button>
			<button
				onclick={() => (viewMode = 'department')}
				class={['flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors', viewMode === 'department' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'].join(' ')}
			>
				<Building2 class="w-3.5 h-3.5" />
				{t('org_view_dept')}
			</button>
		</div>

		{#if viewMode === 'personnel'}
			<div class="flex items-center gap-2">
				<p class="text-xs text-muted-foreground hidden sm:flex items-center gap-1.5">
					<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
					{t('org_agent_hint')}
				</p>
				<!-- Zoom controls -->
				<div class="flex items-center gap-1 rounded-xl border bg-card px-1 py-1 shadow-sm">
					<button
						onclick={zoomOut}
						disabled={zoom <= ZOOM_MIN}
						class="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
						aria-label={t('org_zoom_out')}
					>
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>
					</button>
					<button
						onclick={zoomReset}
						class="min-w-[3.5rem] h-8 rounded-lg px-2 text-xs font-mono font-semibold text-foreground hover:bg-muted transition-colors tabular-nums"
						aria-label={t('org_zoom_reset')}
					>
						{zoomPct}
					</button>
					<button
						onclick={zoomIn}
						disabled={zoom >= ZOOM_MAX}
						class="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
						aria-label={t('org_zoom_in')}
					>
						<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
					</button>
				</div>
			</div>
		{/if}
	</div>

	{#if viewMode === 'personnel'}
		<!-- Chart canvas -->
		<div class="chart-canvas" class:panel-open={selectedAgent !== null}>
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
			<div class="chart-scroll" onwheel={handleWheel} role="img" aria-label={t('org_chart_aria_label')}>
				{#if loading}
					<div class="flex items-center justify-center h-64 gap-2 text-muted-foreground">
						<svg class="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
						<span class="text-sm">{t('loading')}</span>
					</div>
				{:else if loadError}
					<div class="flex items-center justify-center h-64 gap-2 text-destructive text-sm">
						{t('org_load_error')}: {loadError}
					</div>
				{:else}
					<div class="chart-inner" style="transform: scale({zoom}); transform-origin: top center;">
						<OrgChartNode node={tree} onSelect={handleSelect} selectedId={selectedAgent?.id} />
					</div>
				{/if}
			</div>
		</div>

		<!-- Agent Detail Panel -->
		<AgentDetailPanel node={selectedAgent} onClose={handleClose} />

	{:else}
		<!-- Department Tree View -->
		<div class="rounded-xl border bg-card overflow-hidden">
			{#if deptLoading}
				<div class="flex items-center justify-center h-40 gap-2 text-muted-foreground">
					<svg class="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
					<span class="text-sm">{t('loading')}</span>
				</div>
			{:else if deptRoots.length === 0}
				<div class="flex flex-col items-center justify-center py-16 gap-3">
					<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
						<Building2 class="w-6 h-6 text-muted-foreground" />
					</div>
					<p class="text-sm text-muted-foreground">{t('org_dept_empty')}</p>
				</div>
			{:else}
				<div class="divide-y">
					{#each deptRoots as dept (dept.id)}
						{@render deptRow(dept, 0)}
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

{#snippet deptRow(dept: Department, depth: number)}
	{@const stats = deptTotal(dept)}
	{@const expanded = expandedDepts.has(dept.id)}
	{@const hasChildren = (dept.children?.length ?? 0) > 0}

	<div>
		<div
			class="flex items-center gap-3 px-4 py-3 hover:bg-muted/20 transition-colors"
			style="padding-left: {1 + depth * 1.5}rem"
		>
			<button
				onclick={() => toggleDept(dept.id)}
				class="w-5 h-5 flex items-center justify-center text-muted-foreground flex-shrink-0"
				aria-label={expanded ? t('org_collapse') : t('org_expand')}
				disabled={!hasChildren}
			>
				{#if hasChildren}
					{#if expanded}
						<ChevronDown class="w-4 h-4" />
					{:else}
						<ChevronRight class="w-4 h-4" />
					{/if}
				{:else}
					<span class="w-4 h-4 flex items-center justify-center opacity-0">·</span>
				{/if}
			</button>

			<div class="w-8 h-8 rounded-lg bg-amber-50 border border-amber-200 flex items-center justify-center flex-shrink-0">
				<Building2 class="w-4 h-4 text-amber-600" />
			</div>

			<div class="flex-1 min-w-0">
				<div class="flex items-center gap-2">
					<span class="font-medium text-sm">{dept.name}</span>
					{#if dept.status === 'Inactive'}
						<span class="text-xs bg-muted text-muted-foreground px-1.5 py-0.5 rounded">{t('org_dept_inactive')}</span>
					{/if}
				</div>
				{#if dept.description}
					<p class="text-xs text-muted-foreground truncate mt-0.5">{dept.description}</p>
				{/if}
			</div>

			<div class="flex items-center gap-4 text-xs text-muted-foreground flex-shrink-0">
				{#if stats.humans > 0}
					<span class="flex items-center gap-1">
						<div class="w-2 h-2 rounded bg-blue-300"></div>
						{stats.humans} {t('org_human_label')}
					</span>
				{/if}
				{#if stats.agents > 0}
					<span class="flex items-center gap-1">
						<div class="w-2 h-2 rounded bg-violet-300"></div>
						{stats.agents} {t('org_agent_label')}
					</span>
				{/if}
				{#if stats.humans === 0 && stats.agents === 0}
					<span class="italic">{t('org_no_personnel')}</span>
				{/if}
			</div>
		</div>

		{#if expanded && hasChildren}
			<div class="border-t border-dashed border-border/40">
				{#each dept.children! as child (child.id)}
					{@render deptRow(child, depth + 1)}
				{/each}
			</div>
		{/if}
	</div>
{/snippet}

<style>
	.chart-canvas {
		border: 1px solid hsl(var(--border));
		border-radius: 1rem;
		background: hsl(var(--muted) / 0.3);
		overflow: hidden;
		transition: margin-right 0.2s ease;
	}

	@media (min-width: 1024px) {
		.chart-canvas.panel-open {
			margin-right: 340px;
		}
	}

	.chart-scroll {
		overflow-x: auto;
		overflow-y: auto;
		max-height: calc(100vh - 14rem);
		min-height: 400px;
		padding: 3rem 2rem;
		overscroll-behavior: contain;
	}

	.chart-inner {
		display: inline-flex;
		min-width: 100%;
		justify-content: center;
		padding-bottom: 2rem;
		transition: transform 0.15s ease;
	}
</style>
