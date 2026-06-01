<script lang="ts">
	import type { OrgNode } from '$lib/types/org';
	import OrgChartNode from './OrgChartNode.svelte';

	type Props = {
		node: OrgNode;
		onSelect: (node: OrgNode) => void;
		selectedId?: string | null;
	};

	let { node, onSelect, selectedId = null }: Props = $props();

	const isAgent     = $derived(node.type === 'agent');
	const isSelected  = $derived(selectedId === node.id);
	const hasChildren = $derived((node.children?.length ?? 0) > 0);
	const initials    = $derived(
		node.name.split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase()
	);

	const STATUS_COLORS: Record<string, string> = {
		active:   '#22c55e',
		draft:    '#94a3b8',
		inactive: '#f87171'
	};
</script>

<div class="org-node">
	<!-- ── Node Card ── -->
	<!--
	  Agents are interactive (clickable → detail panel).
	  Humans are purely visual (no interaction).
	  Use <button> for agents, <div> for humans.
	-->
	{#if isAgent}
		<button
			class="card card-agent"
			class:card-selected={isSelected}
			onclick={() => onSelect(node)}
			type="button"
			aria-label="{node.name} ajanını görüntüle"
			aria-pressed={isSelected}
		>
			<div class="avatar avatar-agent">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d="M12 8V4H8"></path><rect width="16" height="12" x="4" y="8" rx="2"></rect>
					<path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path>
				</svg>
			</div>
			<div class="info">
				<div class="node-name">{node.name}</div>
				<div class="node-title">{node.title}</div>
				{#if node.model}
					<div class="node-model">{node.model}</div>
				{/if}
			</div>
			<span
				class="status-dot"
				style="background: {STATUS_COLORS[node.agentStatus ?? 'draft']}"
				title={node.agentStatus}
			></span>
		</button>
	{:else}
		<div class="card card-human">
			<div class="avatar avatar-human">{initials}</div>
			<div class="info">
				<div class="node-name">{node.name}</div>
				<div class="node-title">{node.title}</div>
			</div>
		</div>
	{/if}

	<!-- ── Connectors + Children ── -->
	{#if hasChildren}
		<div class="v-line"></div>
		<div class="children-row">
			{#each node.children! as child (child.id)}
				<div class="child-col">
					<div class="h-line"></div>
					<OrgChartNode node={child} {onSelect} {selectedId} />
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	/* ── Tree layout ── */
	.org-node {
		display: flex;
		flex-direction: column;
		align-items: center;
	}

	.v-line {
		width: 2px;
		height: 28px;
		background: hsl(var(--border));
		flex-shrink: 0;
	}

	.h-line {
		width: 2px;
		height: 28px;
		background: hsl(var(--border));
		flex-shrink: 0;
	}

	.children-row {
		display: flex;
		flex-direction: row;
		align-items: flex-start;
	}

	.child-col {
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 0 24px;
		position: relative;
	}

	/* Horizontal bar: spans full width of each child-col.
	   First child: bar starts from its centre (left: 50%).
	   Last child:  bar ends at its centre   (right: 50%).
	   Only child:  no bar at all. */
	.child-col::before {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		height: 2px;
		background: hsl(var(--border));
	}
	.child-col:first-child::before { left: 50%; }
	.child-col:last-child::before  { right: 50%; }
	.child-col:only-child::before  { display: none; }

	/* ── Node card shared ── */
	.card {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		padding: 0.5rem 0.75rem;
		border-radius: 0.875rem;
		border: 1.5px solid hsl(var(--border));
		background: hsl(var(--card));
		width: 210px;
		min-width: 210px;
		position: relative;
		text-align: left;
		transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.1s ease;
		cursor: default;
		user-select: none;
	}

	.card-agent {
		border-color: #c4b5fd;
		background: #f5f3ff;
		cursor: pointer;
	}
	.card-agent:hover {
		border-color: #7c3aed;
		box-shadow: 0 4px 14px rgba(124, 58, 237, 0.15);
		transform: translateY(-1px);
	}
	.card-selected {
		border-color: #7c3aed !important;
		box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.2) !important;
	}

	/* ── Avatar ── */
	.avatar {
		width: 32px;
		height: 32px;
		min-width: 32px;
		border-radius: 0.5rem;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.75rem;
		font-weight: 700;
	}
	.avatar-human { background: #dbeafe; color: #1d4ed8; }
	.avatar-agent { background: #ede9fe; color: #6d28d9; }

	/* ── Text ── */
	.info { min-width: 0; flex: 1; }
	.node-name {
		font-size: 0.8125rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		color: hsl(var(--foreground));
		line-height: 1.3;
	}
	.node-title {
		font-size: 0.6875rem;
		color: hsl(var(--muted-foreground));
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		margin-top: 1px;
		line-height: 1.3;
	}
	.node-model {
		font-size: 0.625rem;
		font-family: ui-monospace, monospace;
		color: #7c3aed;
		margin-top: 2px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ── Status dot (agent only) ── */
	.status-dot {
		width: 7px;
		height: 7px;
		min-width: 7px;
		border-radius: 50%;
		position: absolute;
		top: 7px;
		right: 8px;
	}
</style>
