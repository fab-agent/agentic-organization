<script lang="ts">
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import Table from '$lib/components/ui/table.svelte';
	import { Plus, Pencil, Trash2, Bot, Sparkles, X, Check, ChevronDown } from '@lucide/svelte';

	// ── Types ──────────────────────────────────────────────────────────────────
	type Skill = { name: string; version: string; description: string };

	type Agent = {
		id: number;
		name: string;
		slug: string;
		title: string;
		model: string;
		modelVersion: string;
		status: 'active' | 'draft' | 'inactive';
		department: string;
		responsibleHuman: string;
		jobDescription: string;
		skills: Skill[];
		policies: string[];
	};

	// ── Static data ────────────────────────────────────────────────────────────
	const MODELS = [
		{ value: 'claude-sonnet-4',  label: 'Claude Sonnet 4'  },
		{ value: 'claude-opus-4',    label: 'Claude Opus 4'    },
		{ value: 'gpt-4o',           label: 'GPT-4o'           },
		{ value: 'gemini-2.5-pro',   label: 'Gemini 2.5 Pro'   },
		{ value: 'grok-4.3',         label: 'Grok 4.3'         },
	];

	const DEPARTMENTS = [
		'Yazılım Geliştirme',
		'Kalite Güvence',
		'Pazarlama',
		'Finans',
		'İnsan Kaynakları',
		'Operasyon',
		'Yönetim',
	];

	const HUMANS = [
		'Kuntay Kunt', 'Ahmet Şahin', 'Elif Yıldız',
		'Burak Demir', 'Selin Kaya', 'Mert Arslan',
	];

	/** Policy kütüphanesi: departmana göre önerilen policy'ler */
	const DEPT_POLICIES: Record<string, string[]> = {
		'Yazılım Geliştirme': ['Yazılım Kalite Politikası', 'Güvenlik Politikası', 'Code Review SLA', 'Deployment Politikası'],
		'Kalite Güvence':     ['QA Politikası', 'Test Coverage SLA', 'Bug Raporlama Prosedürü'],
		'Pazarlama':          ['İçerik Politikası', 'Marka Politikası', 'KVKK Uyumluluk', 'Sosyal Medya Kuralları'],
		'Finans':             ['Finans Politikası', 'Uyumluluk Politikası', 'Veri Güvenliği', 'Raporlama SLA'],
		'İnsan Kaynakları':   ['İK Politikası', 'Gizlilik Politikası', 'İşe Alım Prosedürü'],
		'Operasyon':          ['Operasyon Politikası', 'SLA Yönetimi', 'Süreç Dokümantasyon Kuralı'],
		'Yönetim':            ['Şirket Politikası', 'Etik Kurallar', 'Karar Yetki Matrisi'],
	};

	/** Skill kütüphanesi */
	const SKILL_LIBRARY: Skill[] = [
		{ name: 'Code Review',    version: '2.1', description: 'PR inceleme ve best practice kontrolü' },
		{ name: 'TypeScript',     version: '5.x', description: 'Tip güvenliği analizi ve refactor' },
		{ name: 'Git Workflow',   version: '1.0', description: 'Branch stratejisi ve commit standardı' },
		{ name: 'Docker',         version: '24.x', description: 'Container build ve orchestration' },
		{ name: 'GitHub Actions', version: '3.x', description: 'CI/CD pipeline yönetimi' },
		{ name: 'Monitoring',     version: '1.2', description: 'Deploy sonrası sağlık kontrolü' },
		{ name: 'Test Generation',version: '1.3', description: 'Otomatik test yazımı (Playwright/Vitest)' },
		{ name: 'Bug Triage',     version: '1.0', description: 'Hata önceliklendirme ve analiz' },
		{ name: 'Copywriting',    version: '2.0', description: 'Blog ve landing page içerik üretimi' },
		{ name: 'SEO',            version: '1.4', description: 'Anahtar kelime ve içerik optimizasyonu' },
		{ name: 'Social Media',   version: '1.1', description: 'Çoklu platform içerik takvimi' },
		{ name: 'Data Analysis',  version: '1.0', description: 'GA4, Mixpanel ve SQL raporlama' },
		{ name: 'Visualization',  version: '0.9', description: 'Dashboard ve performans raporları' },
		{ name: 'Forecasting',    version: '1.2', description: 'Nakit akışı ve senaryo analizi' },
		{ name: 'Reporting',      version: '2.0', description: 'Aylık/çeyreklik finansal raporlar' },
		{ name: 'Compliance',     version: '1.0', description: 'Vergi ve yasal uyumluluk kontrolü' },
	];

	/** Keyword → skill önerisi haritası */
	const KEYWORD_MAP: Array<[RegExp, string[]]> = [
		[/kod|yazılım|geliştirme|backend|frontend|typescript/i, ['Code Review', 'TypeScript', 'Git Workflow']],
		[/deploy|ci|cd|docker|container|kubernetes/i,           ['Docker', 'GitHub Actions', 'Monitoring']],
		[/test|qa|kalite|hata|bug|selenium/i,                   ['Test Generation', 'Bug Triage']],
		[/pazarlama|içerik|blog|sosyal|marka|seo/i,             ['Copywriting', 'SEO', 'Social Media']],
		[/veri|analiz|analitik|dashboard|rapor|sql/i,           ['Data Analysis', 'Visualization']],
		[/finans|muhasebe|bütçe|fatura|vergi/i,                 ['Forecasting', 'Reporting', 'Compliance']],
	];

	function slugify(text: string): string {
		return text.toLowerCase()
			.replace(/ğ/g,'g').replace(/ş/g,'s').replace(/ı/g,'i')
			.replace(/ö/g,'o').replace(/ü/g,'u').replace(/ç/g,'c')
			.replace(/[^a-z0-9\s-]/g,'').trim()
			.replace(/\s+/g,'-').replace(/-+/g,'-');
	}

	// ── Agent listesi (mock) ────────────────────────────────────────────────────
	let agents: Agent[] = $state([
		{
			id: 1, name: 'CodeGuard', slug: 'codeguard',
			title: 'Code Review Agent', model: 'claude-sonnet-4', modelVersion: '4.6',
			status: 'active', department: 'Yazılım Geliştirme', responsibleHuman: 'Elif Yıldız',
			jobDescription: 'Kod kalitesini artırmak, PR incelemek ve güvenlik açıklarını tespit etmek',
			skills: [
				{ name: 'Code Review', version: '2.1', description: 'PR inceleme ve best practice kontrolü' },
				{ name: 'TypeScript', version: '5.x', description: 'Tip güvenliği analizi ve refactor' },
				{ name: 'Git Workflow', version: '1.0', description: 'Branch stratejisi ve commit standardı' },
			],
			policies: ['Yazılım Kalite Politikası', 'Güvenlik Politikası', 'Code Review SLA'],
		},
		{
			id: 2, name: 'DeployBot', slug: 'deploybot',
			title: 'Deploy & CI Agent', model: 'gpt-4o', modelVersion: '2024-11',
			status: 'active', department: 'Yazılım Geliştirme', responsibleHuman: 'Elif Yıldız',
			jobDescription: 'CI/CD pipeline yönetmek, deployment süreçlerini otomatize etmek',
			skills: [
				{ name: 'Docker', version: '24.x', description: 'Container build ve orchestration' },
				{ name: 'GitHub Actions', version: '3.x', description: 'CI/CD pipeline yönetimi' },
				{ name: 'Monitoring', version: '1.2', description: 'Deploy sonrası sağlık kontrolü' },
			],
			policies: ['Deployment Politikası', 'Güvenlik Politikası'],
		},
		{
			id: 3, name: 'TestMind', slug: 'testmind',
			title: 'QA Automation Agent', model: 'claude-sonnet-4', modelVersion: '4.6',
			status: 'active', department: 'Kalite Güvence', responsibleHuman: 'Burak Demir',
			jobDescription: 'Otomatik test yazımı, hata tespiti ve QA süreçlerini yönetmek',
			skills: [
				{ name: 'Test Generation', version: '1.3', description: 'Otomatik test yazımı' },
				{ name: 'Bug Triage', version: '1.0', description: 'Hata önceliklendirme ve analiz' },
			],
			policies: ['QA Politikası', 'Test Coverage SLA'],
		},
		{
			id: 4, name: 'ContentFlow', slug: 'contentflow',
			title: 'Content & SEO Agent', model: 'claude-sonnet-4', modelVersion: '4.6',
			status: 'active', department: 'Pazarlama', responsibleHuman: 'Selin Kaya',
			jobDescription: 'İçerik üretimi, SEO optimizasyonu ve sosyal medya takvimi',
			skills: [
				{ name: 'Copywriting', version: '2.0', description: 'Blog ve landing page içerik üretimi' },
				{ name: 'SEO', version: '1.4', description: 'Anahtar kelime ve içerik optimizasyonu' },
				{ name: 'Social Media', version: '1.1', description: 'Çoklu platform içerik takvimi' },
			],
			policies: ['İçerik Politikası', 'Marka Politikası', 'KVKK Uyumluluk'],
		},
		{
			id: 5, name: 'DataLens', slug: 'datalens',
			title: 'Analytics Agent', model: 'gemini-2.5-pro', modelVersion: '2025-05',
			status: 'draft', department: 'Pazarlama', responsibleHuman: 'Selin Kaya',
			jobDescription: 'Veri analizi, dashboard oluşturma ve pazarlama raporları',
			skills: [
				{ name: 'Data Analysis', version: '1.0', description: 'GA4 ve SQL raporlama' },
				{ name: 'Visualization', version: '0.9', description: 'Dashboard ve performans raporları' },
			],
			policies: ['Analitik Veri Politikası'],
		},
		{
			id: 6, name: 'LedgerAI', slug: 'ledgerai',
			title: 'Finance & Reporting Agent', model: 'gpt-4o', modelVersion: '2024-11',
			status: 'active', department: 'Finans', responsibleHuman: 'Mert Arslan',
			jobDescription: 'Finansal raporlama, nakit akışı tahmini ve uyumluluk kontrolleri',
			skills: [
				{ name: 'Forecasting', version: '1.2', description: 'Nakit akışı ve senaryo analizi' },
				{ name: 'Reporting', version: '2.0', description: 'Aylık/çeyreklik finansal raporlar' },
				{ name: 'Compliance', version: '1.0', description: 'Vergi ve yasal uyumluluk kontrolü' },
			],
			policies: ['Finans Politikası', 'Uyumluluk Politikası', 'Veri Güvenliği'],
		},
	]);

	// ── Form state ─────────────────────────────────────────────────────────────
	let showPanel      = $state(false);
	let editingAgent: Agent | null = $state(null);

	const emptyForm = () => ({
		name: '', slug: '', title: '',
		model: 'claude-sonnet-4', modelVersion: '',
		status: 'draft' as Agent['status'],
		department: '', responsibleHuman: '',
		jobDescription: '',
		selectedSkills: [] as Skill[],
		selectedPolicies: [] as string[],
	});

	let form = $state(emptyForm());

	// Slug otomatik üret (sadece yeni ajan)
	$effect(() => {
		if (!editingAgent) form.slug = slugify(form.name);
	});

	// Departman değişince önerilen policy'leri otomatik seç
	$effect(() => {
		if (!form.department) return;
		const suggested = DEPT_POLICIES[form.department] ?? [];
		// Mevcut seçili policy'leri koru, yenileri ekle (duplicate olmadan)
		for (const p of suggested) {
			if (!form.selectedPolicies.includes(p)) {
				form.selectedPolicies = [...form.selectedPolicies, p];
			}
		}
	});

	function openCreate() {
		editingAgent = null;
		form = emptyForm();
		suggestedSkills = [];
		showPanel = true;
	}

	function openEdit(agent: Agent) {
		editingAgent = agent;
		form = {
			name:            agent.name,
			slug:            agent.slug,
			title:           agent.title,
			model:           agent.model,
			modelVersion:    agent.modelVersion,
			status:          agent.status,
			department:      agent.department,
			responsibleHuman: agent.responsibleHuman,
			jobDescription:  agent.jobDescription,
			selectedSkills:  [...agent.skills],
			selectedPolicies: [...agent.policies],
		};
		suggestedSkills = [];
		showPanel = true;
	}

	function closePanel() {
		showPanel = false;
		editingAgent = null;
	}

	function saveAgent() {
		if (!form.name || !form.title) return;

		const agentData: Agent = {
			id:               editingAgent?.id ?? Math.max(0, ...agents.map(a => a.id)) + 1,
			name:             form.name,
			slug:             form.slug,
			title:            form.title,
			model:            form.model,
			modelVersion:     form.modelVersion,
			status:           form.status,
			department:       form.department,
			responsibleHuman: form.responsibleHuman,
			jobDescription:   form.jobDescription,
			skills:           form.selectedSkills,
			policies:         form.selectedPolicies,
		};

		if (editingAgent) {
			agents = agents.map(a => a.id === editingAgent!.id ? agentData : a);
		} else {
			agents = [...agents, agentData];
		}
		closePanel();
	}

	// ── Delete ─────────────────────────────────────────────────────────────────
	let deleteTarget: Agent | null = $state(null);
	let showDeleteDialog = $state(false);

	function requestDelete(agent: Agent) { deleteTarget = agent; showDeleteDialog = true; }
	function cancelDelete()              { deleteTarget = null; showDeleteDialog = false; }
	function confirmDelete() {
		if (!deleteTarget) return;
		agents = agents.filter(a => a.id !== deleteTarget!.id);
		cancelDelete();
	}

	// ── Skill kütüphanesi toggle ───────────────────────────────────────────────
	function isSkillSelected(name: string): boolean {
		return form.selectedSkills.some(s => s.name === name);
	}

	function toggleLibrarySkill(skill: Skill) {
		if (isSkillSelected(skill.name)) {
			form.selectedSkills = form.selectedSkills.filter(s => s.name !== skill.name);
		} else {
			form.selectedSkills = [...form.selectedSkills, { ...skill }];
		}
	}

	// ── Custom skill ──────────────────────────────────────────────────────────
	let customSkill = $state({ name: '', version: '', description: '' });

	function addCustomSkill() {
		const { name, version, description } = customSkill;
		if (!name.trim()) return;
		if (isSkillSelected(name)) return;
		form.selectedSkills = [...form.selectedSkills, { name: name.trim(), version: version.trim() || '1.0', description: description.trim() }];
		customSkill = { name: '', version: '', description: '' };
	}

	// ── AI Skill önerisi (simülasyon) ─────────────────────────────────────────
	let isAnalyzing     = $state(false);
	let suggestedSkills: Skill[] = $state([]);

	async function analyzeJobDescription() {
		if (!form.jobDescription.trim()) return;
		isAnalyzing = true;
		suggestedSkills = [];

		await new Promise(r => setTimeout(r, 1600));

		const text = form.jobDescription;
		const found = new Set<string>();
		for (const [pattern, skills] of KEYWORD_MAP) {
			if (pattern.test(text)) skills.forEach(s => found.add(s));
		}

		// Zaten seçili olanları çıkar
		suggestedSkills = SKILL_LIBRARY.filter(
			s => found.has(s.name) && !isSkillSelected(s.name)
		);
		isAnalyzing = false;
	}

	function acceptSuggestion(skill: Skill) {
		form.selectedSkills = [...form.selectedSkills, { ...skill }];
		suggestedSkills = suggestedSkills.filter(s => s.name !== skill.name);
	}

	function dismissSuggestion(skillName: string) {
		suggestedSkills = suggestedSkills.filter(s => s.name !== skillName);
	}

	// ── Policy toggle ─────────────────────────────────────────────────────────
	function togglePolicy(policy: string) {
		if (form.selectedPolicies.includes(policy)) {
			form.selectedPolicies = form.selectedPolicies.filter(p => p !== policy);
		} else {
			form.selectedPolicies = [...form.selectedPolicies, policy];
		}
	}

	let customPolicy = $state('');
	function addCustomPolicy() {
		const p = customPolicy.trim();
		if (!p || form.selectedPolicies.includes(p)) return;
		form.selectedPolicies = [...form.selectedPolicies, p];
		customPolicy = '';
	}

	// ── Helpers ───────────────────────────────────────────────────────────────
	const STATUS_BADGE: Record<string, 'default' | 'secondary' | 'destructive'> = {
		active: 'default', draft: 'secondary', inactive: 'destructive'
	};
	const STATUS_LABEL: Record<string, string> = {
		active: 'Aktif', draft: 'Taslak', inactive: 'Pasif'
	};

	const totalActive = $derived(agents.filter(a => a.status === 'active').length);
	const totalDraft  = $derived(agents.filter(a => a.status === 'draft').length);
</script>

<svelte:head>
	<title>Ajanlar • 3rdParty Agent</title>
</svelte:head>

<!-- ── Page ──────────────────────────────────────────────────────────────── -->
<div class="space-y-6" class:mr-panel={showPanel}>

	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">Ajanlar</h1>
			<p class="text-muted-foreground mt-1">Ajan oluştur, düzenle ve yapılandır</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="h-4 w-4" />
			Yeni Ajan
		</Button>
	</div>

	<!-- Stats -->
	<div class="grid grid-cols-3 gap-3">
		<div class="rounded-xl border bg-card px-4 py-3">
			<div class="text-xs text-muted-foreground">Toplam</div>
			<div class="text-2xl font-semibold tracking-tight mt-0.5">{agents.length}</div>
		</div>
		<div class="rounded-xl border bg-card px-4 py-3">
			<div class="text-xs text-muted-foreground">Aktif</div>
			<div class="text-2xl font-semibold tracking-tight mt-0.5 text-emerald-600">{totalActive}</div>
		</div>
		<div class="rounded-xl border bg-card px-4 py-3">
			<div class="text-xs text-muted-foreground">Taslak</div>
			<div class="text-2xl font-semibold tracking-tight mt-0.5 text-amber-500">{totalDraft}</div>
		</div>
	</div>

	<!-- Table -->
	{#if agents.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-violet-100 flex items-center justify-center">
				<Bot class="w-6 h-6 text-violet-600" />
			</div>
			<div>
				<p class="font-medium">Henüz ajan yok</p>
				<p class="text-sm text-muted-foreground mt-1">İlk ajanı oluşturmak için butona tıklayın.</p>
			</div>
			<Button onclick={openCreate} size="sm" class="mt-2">
				<Plus class="h-4 w-4" /> Yeni Ajan
			</Button>
		</div>
	{:else}
		<div class="rounded-xl border bg-card overflow-hidden">
			<Table>
				<thead>
					<tr class="border-b bg-muted/50 text-left text-sm font-medium text-muted-foreground">
						<th class="h-12 px-4">Ajan</th>
						<th class="h-12 px-4 hidden md:table-cell">Model</th>
						<th class="h-12 px-4 hidden lg:table-cell">Sorumlu</th>
						<th class="h-12 px-4 hidden lg:table-cell">Departman</th>
						<th class="h-12 px-4">Durum</th>
						<th class="h-12 w-[88px] px-4 text-right">İşlemler</th>
					</tr>
				</thead>
				<tbody class="divide-y">
					{#each agents as agent (agent.id)}
						<tr class="hover:bg-muted/30 transition-colors">
							<td class="px-4 py-3">
								<div class="flex items-center gap-3">
									<div class="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
										<Bot class="w-4 h-4 text-violet-600" />
									</div>
									<div>
										<div class="font-medium text-sm">{agent.name}</div>
										<div class="text-xs text-muted-foreground">{agent.title}</div>
									</div>
								</div>
							</td>
							<td class="px-4 py-3 hidden md:table-cell">
								<span class="text-xs font-mono bg-violet-50 text-violet-700 border border-violet-200 rounded-md px-2 py-0.5">
									{agent.model}
								</span>
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell">{agent.responsibleHuman}</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell">{agent.department}</td>
							<td class="px-4 py-3">
								<Badge variant={STATUS_BADGE[agent.status]}>{STATUS_LABEL[agent.status]}</Badge>
							</td>
							<td class="px-4 py-3">
								<div class="flex justify-end gap-1">
									<Button variant="ghost" size="icon" onclick={() => openEdit(agent)} aria-label="Düzenle">
										<Pencil class="h-4 w-4" />
									</Button>
									<Button variant="ghost" size="icon" onclick={() => requestDelete(agent)} aria-label="Sil"
										class="text-destructive hover:text-destructive hover:bg-destructive/10">
										<Trash2 class="h-4 w-4" />
									</Button>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</Table>
		</div>
	{/if}
</div>

<!-- ── Form Panel ────────────────────────────────────────────────────────── -->
{#if showPanel}
	<!-- Backdrop -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/30 z-30 lg:hidden" onclick={closePanel} aria-hidden="true"></div>

	<aside class="agent-panel" aria-label="Ajan Formu">

		<!-- Panel Header -->
		<div class="panel-hdr">
			<div>
				<h2 class="font-display text-lg tracking-tight">
					{editingAgent ? 'Ajanı Düzenle' : 'Yeni Ajan Oluştur'}
				</h2>
				<p class="text-xs text-muted-foreground mt-0.5">
					{editingAgent ? 'Ajan yapılandırmasını güncelleyin.' : 'Yeni bir AI ajan tanımlayın.'}
				</p>
			</div>
			<Button variant="ghost" size="icon" onclick={closePanel} aria-label="Kapat">
				<X class="w-4 h-4" />
			</Button>
		</div>

		<!-- Scrollable body -->
		<div class="panel-body">

			<!-- ① Temel Bilgiler -->
			<section class="form-section">
				<div class="section-title">Temel Bilgiler</div>
				<div class="space-y-3">
					<div class="field">
						<label for="ag-name">Ajan Adı</label>
						<Input id="ag-name" bind:value={form.name} placeholder="CodeGuard" autocomplete="off" />
					</div>
					<div class="field">
						<label for="ag-slug">Slug</label>
						<Input id="ag-slug" bind:value={form.slug} placeholder="codeguard" class="font-mono text-xs" autocomplete="off" />
					</div>
					<div class="field">
						<label for="ag-title">Ünvan / Rol</label>
						<Input id="ag-title" bind:value={form.title} placeholder="Code Review Agent" autocomplete="off" />
					</div>
					<div class="field">
						<label for="ag-status">Durum</label>
						<select id="ag-status" class="select-input" bind:value={form.status}>
							<option value="draft">Taslak</option>
							<option value="active">Aktif</option>
							<option value="inactive">Pasif</option>
						</select>
					</div>
				</div>
			</section>

			<!-- ② Model & Bağlantılar -->
			<section class="form-section">
				<div class="section-title">Model & Bağlantılar</div>
				<div class="space-y-3">
					<div class="grid grid-cols-2 gap-3">
						<div class="field">
							<label for="ag-model">LLM Model</label>
							<select id="ag-model" class="select-input" bind:value={form.model}>
								{#each MODELS as m}
									<option value={m.value}>{m.label}</option>
								{/each}
							</select>
						</div>
						<div class="field">
							<label for="ag-ver">Versiyon</label>
							<Input id="ag-ver" bind:value={form.modelVersion} placeholder="4.6" class="font-mono text-xs" autocomplete="off" />
						</div>
					</div>
					<div class="field">
						<label for="ag-human">Sorumlu Çalışan</label>
						<select id="ag-human" class="select-input" bind:value={form.responsibleHuman}>
							<option value="">— Seçiniz —</option>
							{#each HUMANS as h}
								<option value={h}>{h}</option>
							{/each}
						</select>
					</div>
					<div class="field">
						<label for="ag-dept">Departman</label>
						<select id="ag-dept" class="select-input" bind:value={form.department}>
							<option value="">— Seçiniz —</option>
							{#each DEPARTMENTS as d}
								<option value={d}>{d}</option>
							{/each}
						</select>
						{#if form.department}
							<p class="text-xs text-muted-foreground mt-1">
								Departman policy'leri otomatik eklendi ↓
							</p>
						{/if}
					</div>
				</div>
			</section>

			<!-- ③ İş Tanımı & Skill Önerisi -->
			<section class="form-section">
				<div class="section-title flex items-center justify-between">
					<span>İş Tanımı</span>
					<button
						class="suggest-btn"
						onclick={analyzeJobDescription}
						disabled={isAnalyzing || !form.jobDescription.trim()}
						type="button"
					>
						{#if isAnalyzing}
							<span class="spinner"></span>
							Analiz ediliyor...
						{:else}
							<Sparkles class="w-3.5 h-3.5" />
							Skill Öner
						{/if}
					</button>
				</div>
				<textarea
					class="textarea-input"
					bind:value={form.jobDescription}
					placeholder="Bu ajanın ne yapacağını açıklayın... (örn: Kod kalitesini artırmak, PR incelemek ve güvenlik açıklarını tespit etmek)"
					rows="3"
				></textarea>

				<!-- Önerilen skill'ler -->
				{#if suggestedSkills.length > 0}
					<div class="suggestion-box">
						<div class="text-xs font-semibold text-violet-700 mb-2 flex items-center gap-1.5">
							<Sparkles class="w-3 h-3" />
							Önerilen Yetenekler
						</div>
						<div class="flex flex-wrap gap-2">
							{#each suggestedSkills as skill}
								<div class="suggestion-chip">
									<span>{skill.name}</span>
									<button onclick={() => acceptSuggestion(skill)} type="button" aria-label="Ekle">
										<Check class="w-3 h-3" />
									</button>
									<button onclick={() => dismissSuggestion(skill.name)} type="button" aria-label="Kapat">
										<X class="w-3 h-3" />
									</button>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</section>

			<!-- ④ Skill Kütüphanesi -->
			<section class="form-section">
				<div class="section-title">Yetenekler</div>

				<!-- Library chips -->
				<div class="mb-3">
					<div class="text-xs text-muted-foreground mb-2">Kütüphaneden seç:</div>
					<div class="flex flex-wrap gap-1.5">
						{#each SKILL_LIBRARY as skill}
							{@const selected = isSkillSelected(skill.name)}
							<button
								type="button"
								class="skill-chip"
								class:skill-chip-on={selected}
								onclick={() => toggleLibrarySkill(skill)}
								title={skill.description}
							>
								{#if selected}<Check class="w-3 h-3" />{/if}
								{skill.name}
								<span class="chip-version">v{skill.version}</span>
							</button>
						{/each}
					</div>
				</div>

				<!-- Custom skill -->
				<div class="custom-skill-form">
					<div class="text-xs text-muted-foreground mb-2">Özel yetenek ekle:</div>
					<div class="grid grid-cols-2 gap-2 mb-2">
						<Input bind:value={customSkill.name}        placeholder="Adı"      class="text-xs h-8" />
						<Input bind:value={customSkill.version}     placeholder="Versiyon" class="text-xs h-8 font-mono" />
					</div>
					<div class="flex gap-2">
						<Input bind:value={customSkill.description} placeholder="Kısa açıklama" class="text-xs h-8 flex-1" />
						<Button size="sm" variant="outline" onclick={addCustomSkill} disabled={!customSkill.name.trim()} class="h-8 px-3 text-xs">
							Ekle
						</Button>
					</div>
				</div>

				<!-- Seçili skill listesi -->
				{#if form.selectedSkills.length > 0}
					<div class="mt-3 space-y-1.5">
						<div class="text-xs text-muted-foreground">Seçili ({form.selectedSkills.length}):</div>
						{#each form.selectedSkills as skill}
							<div class="selected-skill-row">
								<div class="flex items-center gap-2 min-w-0">
									<span class="text-sm font-medium truncate">{skill.name}</span>
									<span class="version-badge">v{skill.version}</span>
								</div>
								<button
									type="button"
									onclick={() => { form.selectedSkills = form.selectedSkills.filter(s => s.name !== skill.name); }}
									class="text-muted-foreground hover:text-destructive transition-colors flex-shrink-0"
									aria-label="Kaldır"
								>
									<X class="w-3.5 h-3.5" />
								</button>
							</div>
						{/each}
					</div>
				{/if}
			</section>

			<!-- ⑤ Policy'ler -->
			<section class="form-section">
				<div class="section-title">Policy'ler</div>

				{#if form.department && (DEPT_POLICIES[form.department]?.length ?? 0) > 0}
					<div class="mb-3">
						<div class="text-xs text-muted-foreground mb-2">{form.department} policy'leri:</div>
						<div class="space-y-1.5">
							{#each DEPT_POLICIES[form.department] as policy}
								{@const active = form.selectedPolicies.includes(policy)}
								<button
									type="button"
									class="policy-toggle"
									class:policy-toggle-on={active}
									onclick={() => togglePolicy(policy)}
								>
									<div class="policy-check" class:policy-check-on={active}>
										{#if active}<Check class="w-3 h-3 text-white" />{/if}
									</div>
									<span class="text-sm">{policy}</span>
								</button>
							{/each}
						</div>
					</div>
				{:else if !form.department}
					<p class="text-xs text-muted-foreground mb-3 italic">Departman seçilince ilgili policy'ler otomatik görünür.</p>
				{/if}

				<!-- Custom policy -->
				<div class="flex gap-2">
					<Input
						bind:value={customPolicy}
						placeholder="Policy adı ekle..."
						class="text-xs h-8"
						onkeydown={(e) => e.key === 'Enter' && addCustomPolicy()}
					/>
					<Button size="sm" variant="outline" onclick={addCustomPolicy} disabled={!customPolicy.trim()} class="h-8 px-3 text-xs">
						Ekle
					</Button>
				</div>

				<!-- Seçili policy'ler (departman dışındakiler) -->
				{#each [form.selectedPolicies.filter(p => !(DEPT_POLICIES[form.department] ?? []).includes(p))] as extraPolicies}
					{#if extraPolicies.length > 0}
						<div class="mt-3 space-y-1.5">
							<div class="text-xs text-muted-foreground">Ek policy'ler:</div>
							{#each extraPolicies as policy}
								<div class="selected-skill-row">
									<span class="text-sm">{policy}</span>
									<button
										type="button"
										onclick={() => { form.selectedPolicies = form.selectedPolicies.filter(p => p !== policy); }}
										class="text-muted-foreground hover:text-destructive transition-colors flex-shrink-0"
										aria-label="Kaldır"
									>
										<X class="w-3.5 h-3.5" />
									</button>
								</div>
							{/each}
						</div>
					{/if}
				{/each}
			</section>

		</div>

		<!-- Panel Footer -->
		<div class="panel-footer">
			<Button variant="outline" onclick={closePanel} class="flex-1 sm:flex-none">İptal</Button>
			<Button onclick={saveAgent} disabled={!form.name || !form.title} class="flex-1 sm:flex-none">
				{editingAgent ? 'Güncelle' : 'Oluştur'}
			</Button>
		</div>
	</aside>
{/if}

<!-- ── Delete Dialog ─────────────────────────────────────────────────────── -->
{#if showDeleteDialog}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 animate-backdrop" onclick={cancelDelete}>
		<div class="bg-background w-full max-w-sm rounded-xl border p-6 shadow-lg mx-4 animate-dialog" onclick={(e) => e.stopPropagation()}>
			<h2 class="font-display text-xl tracking-tight">Ajanı Sil</h2>
			<p class="text-sm text-muted-foreground mt-1">
				<strong class="text-foreground">{deleteTarget?.name}</strong> ajanını kalıcı olarak silmek istediğinize emin misiniz?
			</p>
			<div class="flex gap-3 justify-end mt-5">
				<Button variant="outline" onclick={cancelDelete}>İptal</Button>
				<Button variant="destructive" onclick={confirmDelete}>Sil</Button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* Panel margin (content shifts when panel opens on lg+) */
	@media (min-width: 1024px) {
		.mr-panel { margin-right: 608px; transition: margin-right 0.2s ease; }
	}

	/* ── Agent Panel ── */
	.agent-panel {
		position: fixed;
		top: 0; right: 0; bottom: 0;
		width: 600px;
		max-width: 100vw;
		background: hsl(var(--card));
		border-left: 1px solid hsl(var(--border));
		box-shadow: -8px 0 32px rgba(0,0,0,0.1);
		z-index: 40;
		display: flex;
		flex-direction: column;
		animation: panelIn 0.2s cubic-bezier(0.32,0.72,0,1);
	}
	@keyframes panelIn {
		from { transform: translateX(100%); opacity: 0; }
		to   { transform: translateX(0);    opacity: 1; }
	}

	.panel-hdr {
		display: flex; align-items: flex-start;
		justify-content: space-between;
		padding: 1.25rem 1.5rem;
		border-bottom: 1px solid hsl(var(--border));
		flex-shrink: 0;
	}

	.panel-body {
		flex: 1; overflow-y: auto;
		padding: 1.25rem 1.5rem;
		display: flex; flex-direction: column; gap: 1.5rem;
	}

	.panel-footer {
		display: flex; gap: 0.75rem;
		justify-content: flex-end;
		padding: 1rem 1.5rem;
		border-top: 1px solid hsl(var(--border));
		flex-shrink: 0;
		background: hsl(var(--card));
	}

	/* ── Form sections ── */
	.form-section {
		display: flex; flex-direction: column; gap: 0.75rem;
		padding-bottom: 1.5rem;
		border-bottom: 1px solid hsl(var(--border) / 0.6);
	}
	.form-section:last-child { border-bottom: none; padding-bottom: 0; }

	.section-title {
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: hsl(var(--muted-foreground));
		display: flex; align-items: center;
	}

	.field { display: flex; flex-direction: column; gap: 0.375rem; }
	.field label {
		font-size: 0.8125rem;
		font-weight: 500;
		color: hsl(var(--foreground));
	}

	.select-input {
		height: 2.25rem;
		width: 100%;
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--input));
		background: hsl(var(--background));
		padding: 0 0.75rem;
		font-size: 0.875rem;
		color: hsl(var(--foreground));
		transition: border-color 0.15s;
		outline: none;
	}
	.select-input:focus { box-shadow: 0 0 0 1px hsl(var(--ring)); }

	.textarea-input {
		width: 100%;
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--input));
		background: hsl(var(--background));
		padding: 0.5rem 0.75rem;
		font-size: 0.8125rem;
		color: hsl(var(--foreground));
		resize: vertical;
		min-height: 72px;
		outline: none;
		font-family: inherit;
		line-height: 1.5;
		transition: border-color 0.15s;
	}
	.textarea-input::placeholder { color: hsl(var(--muted-foreground)); }
	.textarea-input:focus { box-shadow: 0 0 0 1px hsl(var(--ring)); }

	/* ── Skill Öner button ── */
	.suggest-btn {
		display: inline-flex; align-items: center; gap: 0.375rem;
		font-size: 0.6875rem; font-weight: 600;
		color: #7c3aed;
		background: #f5f3ff;
		border: 1px solid #c4b5fd;
		border-radius: 0.5rem;
		padding: 0.25rem 0.625rem;
		transition: all 0.15s;
		white-space: nowrap;
		cursor: pointer;
	}
	.suggest-btn:hover:not(:disabled) { background: #ede9fe; border-color: #7c3aed; }
	.suggest-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.spinner {
		width: 10px; height: 10px;
		border: 2px solid #c4b5fd;
		border-top-color: #7c3aed;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
		flex-shrink: 0;
	}
	@keyframes spin { to { transform: rotate(360deg); } }

	/* ── Suggestions ── */
	.suggestion-box {
		background: #f5f3ff;
		border: 1px solid #c4b5fd;
		border-radius: 0.75rem;
		padding: 0.75rem;
		margin-top: 0.5rem;
	}
	.suggestion-chip {
		display: inline-flex; align-items: center; gap: 0.25rem;
		background: white;
		border: 1.5px solid #a78bfa;
		border-radius: 999px;
		padding: 0.2rem 0.5rem 0.2rem 0.625rem;
		font-size: 0.6875rem; font-weight: 600; color: #5b21b6;
	}
	.suggestion-chip button {
		display: flex; align-items: center; justify-content: center;
		width: 14px; height: 14px; border-radius: 50%;
		background: none; border: none; cursor: pointer;
		color: #7c3aed; transition: color 0.15s;
	}
	.suggestion-chip button:last-child { color: #94a3b8; }
	.suggestion-chip button:hover { color: #4c1d95; }

	/* ── Skill chips ── */
	.skill-chip {
		display: inline-flex; align-items: center; gap: 0.25rem;
		padding: 0.2rem 0.625rem;
		border-radius: 999px;
		border: 1px solid hsl(var(--border));
		background: hsl(var(--muted) / 0.4);
		font-size: 0.6875rem; font-weight: 500;
		color: hsl(var(--foreground));
		cursor: pointer; transition: all 0.12s;
		white-space: nowrap;
	}
	.skill-chip:hover { border-color: #a78bfa; background: #f5f3ff; color: #6d28d9; }
	.skill-chip-on {
		background: #ede9fe; border-color: #7c3aed;
		color: #5b21b6; font-weight: 600;
	}
	.chip-version { font-size: 0.5625rem; font-family: monospace; color: hsl(var(--muted-foreground)); margin-left: 1px; }

	/* ── Custom skill form ── */
	.custom-skill-form {
		background: hsl(var(--muted) / 0.3);
		border: 1px dashed hsl(var(--border));
		border-radius: 0.75rem;
		padding: 0.75rem;
	}

	/* ── Selected skill row ── */
	.selected-skill-row {
		display: flex; align-items: center;
		justify-content: space-between;
		background: hsl(var(--muted) / 0.4);
		border: 1px solid hsl(var(--border) / 0.6);
		border-radius: 0.625rem;
		padding: 0.4rem 0.625rem;
		gap: 0.5rem;
	}
	.version-badge {
		font-size: 0.5625rem; font-family: monospace;
		background: hsl(var(--muted));
		border-radius: 0.25rem;
		padding: 1px 4px;
		color: hsl(var(--muted-foreground));
		flex-shrink: 0;
	}

	/* ── Policy toggles ── */
	.policy-toggle {
		display: flex; align-items: center; gap: 0.625rem;
		width: 100%;
		background: hsl(var(--muted) / 0.3);
		border: 1px solid hsl(var(--border) / 0.5);
		border-radius: 0.625rem;
		padding: 0.5rem 0.75rem;
		text-align: left; cursor: pointer;
		transition: all 0.12s;
	}
	.policy-toggle:hover { background: hsl(var(--muted) / 0.6); }
	.policy-toggle-on {
		background: #f0fdf4;
		border-color: #86efac;
	}

	.policy-check {
		width: 16px; height: 16px; min-width: 16px;
		border-radius: 0.25rem;
		border: 1.5px solid hsl(var(--border));
		background: white;
		display: flex; align-items: center; justify-content: center;
		transition: all 0.12s;
	}
	.policy-check-on {
		background: #22c55e;
		border-color: #22c55e;
	}
</style>
