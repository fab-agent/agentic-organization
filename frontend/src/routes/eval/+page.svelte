<script lang="ts">
	import { onMount } from 'svelte';
	import { evalApi, type EvalSummary, type RunDiagnosis } from '$lib/api/eval';
	import { personnel as personnelApi, type PersonnelItem } from '$lib/api/personnel';
	import { companyStore } from '$lib/stores/company.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import { Loader } from '@lucide/svelte';

	const activeCompanyId = $derived(companyStore.active?.id ?? '');

	let agents: PersonnelItem[] = $state([]);
	let personaId = $state('');
	let runs: RunDiagnosis[] = $state([]);
	let summary: EvalSummary | null = $state(null);
	let open: string | null = $state(null);
	let loading = $state(false);
	let error: string | null = $state(null);

	const CRITERIA: Record<string, string> = {
		answered: 'Yanıt verdi',
		no_tool_error: 'Araç hatası yok',
		no_policy_block: 'Politika engeli yok'
	};
	const LAYERS: Record<string, string> = {
		model: 'Model',
		prompt: 'Prompt',
		tool: 'Araç',
		policy: 'Politika'
	};

	async function loadAgents() {
		if (!activeCompanyId) return;
		try {
			const all = await personnelApi.list({ company_id: activeCompanyId });
			agents = all.filter((p) => p.type === 'agent');
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function pick() {
		runs = [];
		summary = null;
		open = null;
		error = null;
		if (!personaId) return;
		loading = true;
		try {
			[runs, summary] = await Promise.all([evalApi.runs(personaId), evalApi.summary(personaId)]);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`);

	onMount(loadAgents);
	$effect(() => {
		if (companyStore.active) loadAgents();
	});
</script>

<svelte:head><title>Değerlendirme • fab.engineering</title></svelte:head>

<div class="space-y-6">
	<div>
		<h1 class="font-display text-3xl tracking-tight">Değerlendirme</h1>
		<p class="text-sm text-muted-foreground mt-1">
			Çalışmalar denetim kaydından okunur. Şüpheli katman bir <strong>varsayımdır</strong>, kanıt değildir:
			nereye bakılacağını söyler.
		</p>
	</div>

	<select
		class="h-9 rounded-md border bg-background px-3 text-sm"
		bind:value={personaId}
		onchange={pick}
		aria-label="Ajan"
	>
		<option value="">Ajan seçin…</option>
		{#each agents as a (a.id)}
			<option value={a.id}>{a.name}</option>
		{/each}
	</select>

	{#if error}<p class="text-sm text-destructive">{error}</p>{/if}
	{#if loading}<Loader class="w-4 h-4 animate-spin" />{/if}

	{#if summary}
		<section class="grid gap-3 sm:grid-cols-3" aria-label="Özet">
			{#each Object.entries(summary.criteria) as [id, c] (id)}
				<div class="rounded-lg border p-3">
					<div class="text-xs text-muted-foreground">{CRITERIA[id] ?? id}</div>
					<div class="text-2xl font-semibold">{pct(c.success.share)}</div>
					<div class="text-xs text-muted-foreground">
						%95 aralık {pct(c.success.low)}–{pct(c.success.high)} · {c.success.n} karar
						{#if c.unclear} · {c.unclear} belirsiz{/if}
					</div>
				</div>
			{/each}
		</section>
		{#if Object.keys(summary.suspect_counts).length}
			<p class="text-sm">
				Şüpheli katman sayıları (varsayım):
				{#each Object.entries(summary.suspect_counts) as [layer, n] (layer)}
					<Badge variant="outline" class="ml-1">{LAYERS[layer] ?? layer}: {n}</Badge>
				{/each}
			</p>
		{/if}
	{/if}

	{#if runs.length}
		<div class="overflow-x-auto rounded-lg border">
			<table class="w-full text-sm">
				<thead class="text-left text-xs text-muted-foreground">
					<tr>
						<th class="p-2">Çalışma</th><th class="p-2">Şüpheli katman</th>
						<th class="p-2">Bulgu</th><th class="p-2">Olay</th><th class="p-2">Güncelleme</th>
					</tr>
				</thead>
				<tbody>
					{#each runs as r (r.run_id)}
						<tr class="border-t cursor-pointer hover:bg-muted/40" onclick={() => (open = open === r.run_id ? null : r.run_id)}>
							<td class="p-2 font-mono text-xs">{r.run_id}</td>
							<td class="p-2">{r.suspect_layer ? (LAYERS[r.suspect_layer] ?? r.suspect_layer) : '—'}</td>
							<td class="p-2">{r.findings.length}</td>
							<td class="p-2">{r.events_seen}{#if r.truncated} (kesildi){/if}</td>
							<td class="p-2 text-xs">{new Date(r.updated_at).toLocaleString()}</td>
						</tr>
						{#if open === r.run_id}
							<tr class="border-t bg-muted/20">
								<td colspan="5" class="p-3">
									{#if r.findings.length === 0}
										<span class="text-muted-foreground">Bulgu yok (sinyal yok, sorun yok demek değildir).</span>
									{:else}
										<ul class="space-y-1">
											{#each r.findings as f}
												<li>
													<Badge variant="outline">{LAYERS[f.layer] ?? f.layer}</Badge>
													<span class="ml-2">{f.kind}</span>
													<span class="ml-2 text-muted-foreground">{f.severity} · {f.detail}</span>
												</li>
											{/each}
										</ul>
									{/if}
									{#if r.ignored_client_claims}
										<p class="mt-2 text-xs text-muted-foreground">{r.ignored_client_claims} istemci iddiası yok sayıldı.</p>
									{/if}
								</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
		</div>
	{:else if personaId && !loading}
		<p class="text-sm text-muted-foreground">Kayıtlı teşhis yok.</p>
	{/if}
</div>
