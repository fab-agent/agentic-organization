<script lang="ts">
	import type { OrgNode } from '$lib/types/org';
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';

	type Props = {
		node: OrgNode | null;
		onClose: () => void;
	};

	let { node, onClose }: Props = $props();

	const statusLabel: Record<string, string> = {
		active: 'Aktif',
		draft:  'Taslak',
		inactive: 'Pasif'
	};
</script>

{#if node}
	<!-- Mobile backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="fixed inset-0 bg-black/30 z-20 lg:hidden"
		onclick={onClose}
		aria-hidden="true"
	></div>

	<!-- Panel -->
	<aside class="panel" aria-label="Ajan Detayı">
		<!-- Header -->
		<div class="panel-header">
			<div class="flex items-center gap-3">
				<div class="w-10 h-10 rounded-xl bg-violet-100 flex items-center justify-center flex-shrink-0">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6d28d9" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
						<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/>
						<path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>
					</svg>
				</div>
				<div class="min-w-0">
					<div class="font-semibold text-sm truncate">{node.name}</div>
					<div class="text-xs text-muted-foreground truncate">{node.title}</div>
				</div>
			</div>
			<Button variant="ghost" size="icon" onclick={onClose} aria-label="Kapat" class="flex-shrink-0">
				<!-- X icon inline to avoid another import -->
				<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d="M18 6 6 18"/><path d="m6 6 12 12"/>
				</svg>
			</Button>
		</div>

		<!-- Scrollable body -->
		<div class="panel-body">

			<!-- Status + Model row -->
			<div class="flex flex-wrap gap-2 items-center">
				<Badge variant={node.agentStatus === 'active' ? 'default' : 'secondary'}>
					{statusLabel[node.agentStatus ?? 'draft'] ?? 'Taslak'}
				</Badge>
				{#if node.model}
					<span class="model-pill">{node.model}</span>
				{/if}
				{#if node.modelVersion}
					<span class="text-xs text-muted-foreground">v{node.modelVersion}</span>
				{/if}
			</div>

			<!-- Departman -->
			<section class="section">
				<div class="section-label">Departman</div>
				<div class="text-sm">{node.department}</div>
			</section>

			<!-- Sorumlu çalışan -->
			{#if node.responsibleHuman}
				<section class="section">
					<div class="section-label flex items-center gap-1.5">
						<!-- User icon -->
						<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
							<path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
							<circle cx="12" cy="7" r="4"/>
						</svg>
						Sorumlu Çalışan
					</div>
					<div class="human-chip">
						<div class="human-avatar">{node.responsibleHuman.charAt(0)}</div>
						<span class="text-sm font-medium">{node.responsibleHuman}</span>
					</div>
				</section>
			{/if}

			<!-- Skills -->
			{#if node.skills?.length}
				<section class="section">
					<div class="section-label flex items-center gap-1.5">
						<!-- Wrench icon -->
						<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
							<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
						</svg>
						Yetenekler
					</div>
					<div class="space-y-2">
						{#each node.skills as skill}
							<div class="skill-card">
								<div class="flex items-center justify-between mb-0.5">
									<span class="text-sm font-medium">{skill.name}</span>
									<span class="version-tag">v{skill.version}</span>
								</div>
								<p class="text-xs text-muted-foreground leading-relaxed">{skill.description}</p>
							</div>
						{/each}
					</div>
				</section>
			{/if}

			<!-- Policies -->
			{#if node.policies?.length}
				<section class="section">
					<div class="section-label flex items-center gap-1.5">
						<!-- Shield icon -->
						<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
							<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
						</svg>
						Bağlı Policy'ler
					</div>
					<div class="space-y-1.5">
						{#each node.policies as policy}
							<div class="policy-row">
								<div class="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0 mt-0.5"></div>
								<span class="text-sm">{policy}</span>
							</div>
						{/each}
					</div>
				</section>
			{/if}

		</div>
	</aside>
{/if}

<style>
	.panel {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: 320px;
		background: hsl(var(--card));
		border-left: 1px solid hsl(var(--border));
		box-shadow: -4px 0 24px rgba(0, 0, 0, 0.08);
		z-index: 30;
		display: flex;
		flex-direction: column;
		animation: panelSlideIn 0.2s cubic-bezier(0.32, 0.72, 0, 1);
	}

	@keyframes panelSlideIn {
		from { transform: translateX(100%); opacity: 0; }
		to   { transform: translateX(0);    opacity: 1; }
	}

	.panel-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid hsl(var(--border));
		flex-shrink: 0;
	}

	.panel-body {
		flex: 1;
		overflow-y: auto;
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.model-pill {
		font-size: 0.6875rem;
		font-family: ui-monospace, monospace;
		background: #ede9fe;
		color: #6d28d9;
		border: 1px solid #c4b5fd;
		border-radius: 0.375rem;
		padding: 1px 7px;
	}

	.section {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.section-label {
		font-size: 0.6875rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: hsl(var(--muted-foreground));
	}

	.human-chip {
		display: flex;
		align-items: center;
		gap: 0.625rem;
		background: hsl(var(--muted) / 0.6);
		border-radius: 0.875rem;
		padding: 0.5rem 0.75rem;
	}

	.human-avatar {
		width: 32px;
		height: 32px;
		border-radius: 0.5rem;
		background: #dbeafe;
		color: #1d4ed8;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.8125rem;
		font-weight: 700;
		flex-shrink: 0;
	}

	.skill-card {
		background: hsl(var(--muted) / 0.4);
		border: 1px solid hsl(var(--border) / 0.6);
		border-radius: 0.75rem;
		padding: 0.625rem 0.75rem;
	}

	.version-tag {
		font-size: 0.625rem;
		font-family: ui-monospace, monospace;
		background: hsl(var(--muted));
		border-radius: 0.25rem;
		padding: 1px 5px;
		color: hsl(var(--muted-foreground));
	}

	.policy-row {
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		background: hsl(var(--muted) / 0.4);
		border: 1px solid hsl(var(--border) / 0.6);
		border-radius: 0.625rem;
		padding: 0.5rem 0.75rem;
	}
</style>
