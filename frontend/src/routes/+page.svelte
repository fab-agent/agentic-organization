<script lang="ts">
	import { onMount } from 'svelte';
	import Button from '$lib/components/ui/button.svelte';
	import Card from '$lib/components/ui/card.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import { Plus, Building2, Edit, X, Target, ShieldCheck, Loader, AlertCircle } from '@lucide/svelte';
	import { departments as deptApi } from '$lib/api/departments';
	import { personnel } from '$lib/api/personnel';

	// ── Live stats ─────────────────────────────────────────────────────────────
	let statsLoading = $state(true);
	let totalPersonnel = $state(0);
	let activeAgents   = $state(0);
	let totalDepts     = $state(0);
	let totalPolicies  = $state(0);

	onMount(async () => {
		try {
			const [depts, people] = await Promise.all([deptApi.list(), personnel.list()]);
			totalPersonnel = people.length;
			activeAgents   = people.filter(p => p.agent_config?.status === 'active').length;
			totalDepts     = depts.length;
			totalPolicies  = depts.reduce((s, d) => s + d.policies.length, 0);
		} finally {
			statsLoading = false;
		}
	});

	// ── Company edit panel ─────────────────────────────────────────────────────
	let panelOpen = $state(false);

	type Goal = { id: number; text: string; done: boolean };
	type CompanyData = {
		name: string;
		sector: string;
		website: string;
		vision: string;
		mission: string;
		values: string[];
		goals: Goal[];
	};

	let company: CompanyData = $state({
		name: 'Acme Corp',
		sector: 'Yazılım & SaaS',
		website: 'https://acmecorp.example.com',
		vision: 'Teknoloji ile iş süreçlerini dönüştüren, insan-ajan iş birliğinde sektörün referans noktası olmak.',
		mission: 'Kurumların agentic süreçleri güvenli, izlenebilir ve yönetilebilir biçimde devreye almasını sağlamak.',
		values: ['Şeffaflık', 'Güven', 'Sürekli Öğrenme', 'İnsan Odaklılık', 'Ölçülebilir Etki'],
		goals: [
			{ id: 1, text: 'Agentic süreçleri 5 departmanda devreye almak', done: false },
			{ id: 2, text: '15 aktif ajan oluşturmak', done: false },
			{ id: 3, text: 'Tüm departmanlara özel policy kütüphanesi oluşturmak', done: false },
			{ id: 4, text: 'Ajan performans izleme dashboard\'unu kurmak', done: false },
		]
	});

	let editCompany: CompanyData = $state({ ...company, values: [...company.values], goals: company.goals.map(g => ({...g})) });
	let newValue = $state('');
	let newGoal  = $state('');

	function openPanel() {
		editCompany = {
			...company,
			values: [...company.values],
			goals: company.goals.map(g => ({ ...g }))
		};
		newValue = '';
		newGoal  = '';
		panelOpen = true;
	}

	function saveCompany() {
		company = { ...editCompany, values: [...editCompany.values], goals: editCompany.goals.map(g => ({...g})) };
		panelOpen = false;
	}

	function addValue() {
		const v = newValue.trim();
		if (!v || editCompany.values.includes(v)) return;
		editCompany.values = [...editCompany.values, v];
		newValue = '';
	}

	function removeValue(v: string) {
		editCompany.values = editCompany.values.filter(x => x !== v);
	}

	function addGoal() {
		const t = newGoal.trim();
		if (!t) return;
		const maxId = editCompany.goals.reduce((m, g) => Math.max(m, g.id), 0);
		editCompany.goals = [...editCompany.goals, { id: maxId + 1, text: t, done: false }];
		newGoal = '';
	}

	function removeGoal(id: number) {
		editCompany.goals = editCompany.goals.filter(g => g.id !== id);
	}
</script>

<svelte:head>
	<title>Dashboard • 3rdParty Agent</title>
</svelte:head>

<div class={['space-y-8 transition-all duration-200', panelOpen ? 'lg:mr-[600px]' : ''].join(' ')}>

	<!-- Header -->
	<div class="flex items-end justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">Dashboard</h1>
			<p class="text-muted-foreground mt-1.5">{company.name} • Genel bakış</p>
		</div>
		<a href="/personnel">
			<Button class="gap-x-2">
				<Plus class="w-4 h-4" />
				<span>Yeni Personel</span>
			</Button>
		</a>
	</div>

	<!-- Stats Cards -->
	<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
		{#each [
			{ label: 'Toplam Personel', value: totalPersonnel, color: '' },
			{ label: 'Aktif Ajan',      value: activeAgents,   color: 'text-emerald-600' },
			{ label: 'Departman',       value: totalDepts,     color: '' },
			{ label: 'Policy Tanımı',   value: totalPolicies,  color: '' },
		] as stat}
			<Card class="p-6">
				<div class="text-sm text-muted-foreground">{stat.label}</div>
				{#if statsLoading}
					<div class="mt-2 h-10 w-16 rounded-lg bg-muted animate-pulse"></div>
				{:else}
					<div class="text-4xl font-semibold tracking-tighter mt-2 {stat.color}">{stat.value}</div>
				{/if}
			</Card>
		{/each}
	</div>

	<!-- company.md preview -->
	<Card class="p-6">
		<div class="flex items-center justify-between mb-5">
			<div class="flex items-center gap-x-3">
				<div class="w-9 h-9 rounded-xl bg-muted flex items-center justify-center">
					<Building2 class="w-4 h-4 text-muted-foreground" />
				</div>
				<div>
					<div class="font-semibold tracking-tight">company.md</div>
					<div class="text-xs text-muted-foreground">Vizyon • Misyon • Değerler • Hedefler</div>
				</div>
			</div>

			<Button variant="outline" size="sm" class="gap-x-2 text-xs h-8" onclick={openPanel}>
				<Edit class="w-3.5 h-3.5" />
				<span>Düzenle</span>
			</Button>
		</div>

		<div class="space-y-4 text-sm">
			<div>
				<div class="font-semibold text-base">{company.name}</div>
				<div class="text-xs text-muted-foreground mt-0.5">{company.sector}</div>
			</div>

			<div class="space-y-1">
				<div class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Vizyon</div>
				<p class="text-muted-foreground leading-relaxed">{company.vision}</p>
			</div>

			<div class="space-y-1">
				<div class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Misyon</div>
				<p class="text-muted-foreground leading-relaxed">{company.mission}</p>
			</div>

			{#if company.values.length > 0}
				<div class="space-y-2">
					<div class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Değerler</div>
					<div class="flex flex-wrap gap-1.5">
						{#each company.values as val}
							<span class="px-2.5 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-medium">{val}</span>
						{/each}
					</div>
				</div>
			{/if}

			{#if company.goals.length > 0}
				<div class="space-y-2">
					<div class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Hedefler</div>
					<ul class="space-y-1.5">
						{#each company.goals as goal}
							<li class="flex items-start gap-x-2.5">
								<div class="mt-0.5 w-4 h-4 rounded bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center flex-shrink-0">
									<div class="w-2 h-2 rounded-sm bg-emerald-500"></div>
								</div>
								<span class="text-muted-foreground">{goal.text}</span>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
		</div>
	</Card>
</div>

<!-- ── Company Edit Panel ────────────────────────────────────────────────────── -->
<div
	class={[
		'fixed top-0 right-0 h-full w-full max-w-[600px] bg-background border-l shadow-xl z-40',
		'flex flex-col transition-transform duration-200 ease-out',
		panelOpen ? 'translate-x-0' : 'translate-x-full'
	].join(' ')}
	aria-label="Şirket bilgilerini düzenle"
>
	<!-- Header -->
	<div class="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
		<div class="flex items-center gap-2.5">
			<div class="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
				<Building2 class="w-4 h-4 text-muted-foreground" />
			</div>
			<div>
				<div class="font-semibold text-sm">Şirket Bilgileri</div>
				<div class="text-xs text-muted-foreground">company.md içeriğini düzenle</div>
			</div>
		</div>
		<Button variant="ghost" size="icon" onclick={() => (panelOpen = false)} aria-label="Kapat">
			<X class="w-4 h-4" />
		</Button>
	</div>

	<!-- Body -->
	<div class="flex-1 overflow-y-auto px-6 py-5 space-y-7">

		<!-- ① Kimlik -->
		<section class="space-y-4">
			<div class="section-label"><span class="section-badge">1</span>Şirket Kimliği</div>
			<div class="grid sm:grid-cols-2 gap-4">
				<div class="space-y-1.5 sm:col-span-2">
					<label class="text-sm font-medium" for="co-name">Şirket Adı</label>
					<Input id="co-name" bind:value={editCompany.name} placeholder="Acme Corp" />
				</div>
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="co-sector">Sektör</label>
					<Input id="co-sector" bind:value={editCompany.sector} placeholder="Yazılım & SaaS" />
				</div>
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="co-web">Website</label>
					<Input id="co-web" bind:value={editCompany.website} placeholder="https://..." />
				</div>
			</div>
		</section>

		<!-- ② Vizyon & Misyon -->
		<section class="space-y-4">
			<div class="section-label"><span class="section-badge">2</span>Vizyon & Misyon</div>
			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="co-vision">Vizyon</label>
				<textarea id="co-vision" bind:value={editCompany.vision}
					class="textarea" rows="3"
					placeholder="Uzun vadeli varılmak istenen nokta..."></textarea>
			</div>
			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="co-mission">Misyon</label>
				<textarea id="co-mission" bind:value={editCompany.mission}
					class="textarea" rows="3"
					placeholder="Günlük operasyonda odaklanılan amaç..."></textarea>
			</div>
		</section>

		<!-- ③ Değerler -->
		<section class="space-y-4">
			<div class="section-label"><span class="section-badge">3</span>Şirket Değerleri</div>
			{#if editCompany.values.length > 0}
				<div class="flex flex-wrap gap-2">
					{#each editCompany.values as val}
						<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium">
							{val}
							<button type="button" onclick={() => removeValue(val)} class="hover:text-destructive transition-colors" aria-label="Kaldır">
								<X class="w-3 h-3" />
							</button>
						</span>
					{/each}
				</div>
			{/if}
			<div class="flex gap-2">
				<Input bind:value={newValue} placeholder="Yeni değer..." onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addValue(); } }} class="flex-1" />
				<Button variant="outline" onclick={addValue} disabled={!newValue.trim()}>
					<Plus class="w-3.5 h-3.5" />
					Ekle
				</Button>
			</div>
		</section>

		<!-- ④ Hedefler -->
		<section class="space-y-4">
			<div class="section-label"><span class="section-badge">4</span>Şirket Hedefleri</div>
			{#if editCompany.goals.length > 0}
				<div class="space-y-2">
					{#each editCompany.goals as goal}
						<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/60 border border-border/50 group/goal">
							<div class="w-3.5 h-3.5 rounded-sm bg-emerald-500/20 border border-emerald-500/50 flex-shrink-0"></div>
							<span class="text-sm flex-1">{goal.text}</span>
							<button type="button" onclick={() => removeGoal(goal.id)}
								class="text-muted-foreground hover:text-destructive transition-colors opacity-0 group-hover/goal:opacity-100"
								aria-label="Kaldır">
								<X class="w-3.5 h-3.5" />
							</button>
						</div>
					{/each}
				</div>
			{/if}
			<div class="flex gap-2">
				<Input bind:value={newGoal} placeholder="Yeni hedef..." onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addGoal(); } }} class="flex-1" />
				<Button variant="outline" onclick={addGoal} disabled={!newGoal.trim()}>
					<Plus class="w-3.5 h-3.5" />
					Ekle
				</Button>
			</div>
		</section>

	</div>

	<!-- Footer -->
	<div class="border-t px-6 py-4 flex gap-3 justify-end flex-shrink-0 bg-background">
		<Button variant="outline" onclick={() => (panelOpen = false)}>İptal</Button>
		<Button onclick={saveCompany}>Kaydet</Button>
	</div>
</div>

{#if panelOpen}
	<div class="fixed inset-0 z-30 bg-black/40 lg:hidden" onclick={() => (panelOpen = false)} aria-hidden="true"></div>
{/if}

<style>
	.section-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.6875rem;
		font-weight: 700;
		color: hsl(var(--muted-foreground));
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}
	.section-badge {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 1.25rem;
		height: 1.25rem;
		border-radius: 9999px;
		background: hsl(var(--primary) / 0.1);
		color: hsl(var(--primary));
		font-size: 0.625rem;
		font-weight: 700;
		flex-shrink: 0;
	}
	.textarea {
		display: flex;
		width: 100%;
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--input));
		background: hsl(var(--background));
		padding: 0.5rem 0.75rem;
		font-size: 0.875rem;
		box-shadow: var(--shadow-sm);
		resize: vertical;
		outline: none;
	}
	.textarea:focus-visible {
		ring: 1px solid hsl(var(--ring));
	}
</style>
