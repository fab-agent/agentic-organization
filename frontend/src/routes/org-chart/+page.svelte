<script lang="ts">
	import { onMount } from 'svelte';
	import OrgChartNode from '$lib/components/OrgChartNode.svelte';
	import AgentDetailPanel from '$lib/components/AgentDetailPanel.svelte';
	import type { OrgNode } from '$lib/types/org';
	import { orgTree } from '$lib/api/orgtree';

	// ── Data ──────────────────────────────────────────────────────────────────
	let roots: OrgNode[] = $state([]);
	let loading = $state(true);
	let loadError: string | null = $state(null);

	// If API returns multiple roots wrap them in a synthetic node
	const tree: OrgNode = $derived(
		roots.length === 1
			? roots[0]
			: { id: '__root__', name: 'Şirket', title: '', type: 'human', department: null, children: roots }
	);

	onMount(async () => {
		try {
			roots = await orgTree.get();
		} catch (e) {
			loadError = (e as Error).message;
		} finally {
			loading = false;
		}
	});

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
</script>

<svelte:head>
	<title>Org Şeması • 3rdParty Agent</title>
</svelte:head>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">Org Şeması</h1>
			<p class="text-muted-foreground mt-1">Organizasyon hiyerarşisi ve ajan dağılımı</p>
		</div>

		<!-- Legend -->
		{#if !loading && roots.length > 0}
			<div class="flex items-center gap-4 text-sm">
				<div class="flex items-center gap-2">
					<div class="w-3 h-3 rounded bg-blue-200 border border-blue-400"></div>
					<span class="text-muted-foreground">{totalHumans} İnsan</span>
				</div>
				<div class="flex items-center gap-2">
					<div class="w-3 h-3 rounded bg-violet-200 border border-violet-400"></div>
					<span class="text-muted-foreground">{totalAgents} Ajan <span class="text-emerald-600">({activeAgents} aktif)</span></span>
				</div>
			</div>
		{/if}
	</div>

	<!-- Toolbar -->
	<div class="flex items-center justify-between">
		<p class="text-xs text-muted-foreground flex items-center gap-1.5">
			<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
			Mor ajan kartlarına tıklayarak detayları görüntüleyebilirsiniz
		</p>

		<!-- Zoom controls -->
		<div class="flex items-center gap-1 rounded-xl border bg-card px-1 py-1 shadow-sm">
			<button
				onclick={zoomOut}
				disabled={zoom <= ZOOM_MIN}
				class="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
				aria-label="Uzaklaştır"
			>
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="5" y1="12" x2="19" y2="12"/></svg>
			</button>

			<button
				onclick={zoomReset}
				class="min-w-[3.5rem] h-8 rounded-lg px-2 text-xs font-mono font-semibold text-foreground hover:bg-muted transition-colors tabular-nums"
				aria-label="Orijinal boyuta sıfırla"
			>
				{zoomPct}
			</button>

			<button
				onclick={zoomIn}
				disabled={zoom >= ZOOM_MAX}
				class="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
				aria-label="Yakınlaştır"
			>
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
			</button>
		</div>
	</div>

	<!-- Chart canvas -->
	<div class="chart-canvas" class:panel-open={selectedAgent !== null}>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div class="chart-scroll" onwheel={handleWheel} role="img" aria-label="Organizasyon şeması">
			{#if loading}
				<div class="flex items-center justify-center h-64 gap-2 text-muted-foreground">
					<svg class="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
					<span class="text-sm">Yükleniyor...</span>
				</div>
			{:else if loadError}
				<div class="flex items-center justify-center h-64 gap-2 text-destructive text-sm">
					Yüklenemedi: {loadError}
				</div>
			{:else}
				<div class="chart-inner" style="transform: scale({zoom}); transform-origin: top center;">
					<OrgChartNode node={tree} onSelect={handleSelect} selectedId={selectedAgent?.id} />
				</div>
			{/if}
		</div>
	</div>
</div>

<!-- Agent Detail Panel -->
<AgentDetailPanel node={selectedAgent} onClose={handleClose} />

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
