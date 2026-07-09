<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import Button from '$lib/components/ui/button.svelte';
	import {
		Cpu,
		Building,
		UserRound,
		Bot,
		Layers,
		GitBranch,
		BriefcaseBusiness,
		ArrowLeftRight,
		ChevronDown,
		Menu,
		X,
		Settings,
		Building2,
		Plus,
		Globe,
		Check,
		LogOut,
		GitPullRequest,
		Zap,
		Inbox,
		ChevronLeft,
		ChevronRight,
		Settings2,
		Edit,
		Trash2,
	} from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { companyStore } from '$lib/stores/company.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { i18n, type Locale } from '$lib/i18n/index.svelte';
	import type { Company } from '$lib/api/companies';
	import { a2aApi } from '$lib/api/a2a';
	import Input from '$lib/components/ui/input.svelte';

	let { children }: { children: Snippet } = $props();

	const PUBLIC_ROUTES = ['/login', '/set-password', '/request-reset', '/setup'];

	let sidebarOpen      = $state(false);   // mobile drawer
	let sidebarCollapsed = $state(false);   // desktop collapse
	let companyMenuOpen  = $state(false);
	let langMenuOpen     = $state(false);
	let addingCompany    = $state(false);
	let newCompanyName   = $state('');
	let addError         = $state('');
	let adding           = $state(false);
	let a2aPendingCount  = $state(0);

	const locales: { code: Locale; label: string; flag: string }[] = [
		{ code: 'tr', label: 'Türkçe', flag: '🇹🇷' },
		{ code: 'en', label: 'English', flag: '🇬🇧' },
	];

	function t(key: Parameters<typeof i18n.t>[0]) {
		return i18n.t(key);
	}

	$effect(() => {
		$page.url.pathname;
		sidebarOpen = false;
		companyMenuOpen = false;
		langMenuOpen = false;
	});

	onMount(() => {
		(async () => {
			try {
				const { API_URL } = await import('$lib/api/client');
				const res = await fetch(`${API_URL}/auth/setup-status`);
				if (res.ok) {
					const { needs_setup } = await res.json();
					if (needs_setup && $page.url.pathname !== '/setup') { goto('/setup'); return; }
				}
			} catch {}

			await authStore.init();
			const path = $page.url.pathname;
			const isPublic = PUBLIC_ROUTES.some(r => path.startsWith(r));
			if (!authStore.isLoggedIn && !isPublic) { goto('/login'); return; }
			if (authStore.isLoggedIn && authStore.user?.must_change_password && path !== '/set-password') {
				goto('/set-password'); return;
			}
			if (authStore.isLoggedIn) await loadCompanies();
		})();
		const timer = setInterval(loadA2ACount, 30000);
		return () => clearInterval(timer);
	});

	$effect(() => { if (authStore.isLoggedIn && !companyStore.loaded) loadCompanies(); });
	$effect(() => { if (companyStore.active) loadA2ACount(); });

	async function loadCompanies() {
		const preferredIds = authStore.user?.companies.map(c => c.company_id);
		await companyStore.load(preferredIds);
	}

	async function loadA2ACount() {
		if (!authStore.isLoggedIn) return;
		try {
			const { count } = await a2aApi.pendingCount(companyStore.active?.id);
			a2aPendingCount = count;
		} catch {}
	}

	async function handleAddCompany() {
		if (!newCompanyName.trim()) return;
		adding = true; addError = '';
		try {
			await companyStore.create(newCompanyName.trim());
			newCompanyName = ''; addingCompany = false; companyMenuOpen = false;
		} catch (e: any) {
			addError = e?.message ?? 'Hata oluştu';
		} finally { adding = false; }
	}

	function selectCompany(c: Company) { companyStore.setActive(c); companyMenuOpen = false; }

	const currentLang  = $derived(locales.find(l => l.code === i18n.locale)!);
	const active       = $derived(companyStore.active);
	const companyList  = $derived(companyStore.list);
	const currentUser  = $derived(authStore.user);
	const userInitials = $derived(
		currentUser?.name?.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase() ?? '??'
	);

	function logout() { authStore.logout(); goto('/login'); }

	const isPublicPage = $derived(PUBLIC_ROUTES.some(r => $page.url.pathname.startsWith(r)));

	// ── Company.md panel ──────────────────────────────────────────────────────
	type Goal = { id: number; text: string; done: boolean };
	type CompanyMd = {
		name: string; sector: string; website: string;
		vision: string; mission: string;
		values: string[]; goals: Goal[];
	};

	let coMdOpen = $state(false);
	let coMdEdit = $state<CompanyMd>({
		name: '', sector: '', website: '',
		vision: 'Teknoloji ile iş süreçlerini dönüştüren, insan-ajan iş birliğinde sektörün referans noktası olmak.',
		mission: 'Kurumların agentic süreçleri güvenli, izlenebilir ve yönetilebilir biçimde devreye almasını sağlamak.',
		values: ['Şeffaflık', 'Güven', 'Sürekli Öğrenme', 'İnsan Odaklılık', 'Ölçülebilir Etki'],
		goals: [
			{ id: 1, text: 'Agentic süreçleri 5 departmanda devreye almak', done: false },
			{ id: 2, text: '15 aktif ajan oluşturmak', done: false },
			{ id: 3, text: 'Tüm departmanlara özel policy kütüphanesi oluşturmak', done: false },
		],
	});
	let coNewValue = $state('');
	let coNewGoal  = $state('');

	function openCoMd() {
		coMdEdit = {
			...coMdEdit,
			name: active?.name ?? coMdEdit.name,
			sector: (active as any)?.sector ?? coMdEdit.sector,
			website: (active as any)?.website ?? coMdEdit.website,
			values: [...coMdEdit.values],
			goals: coMdEdit.goals.map(g => ({ ...g })),
		};
		coNewValue = ''; coNewGoal = '';
		coMdOpen = true;
		companyMenuOpen = false;
	}

	function coAddValue() {
		const v = coNewValue.trim();
		if (!v || coMdEdit.values.includes(v)) return;
		coMdEdit = { ...coMdEdit, values: [...coMdEdit.values, v] };
		coNewValue = '';
	}
	function coRemoveValue(v: string) {
		coMdEdit = { ...coMdEdit, values: coMdEdit.values.filter(x => x !== v) };
	}
	function coAddGoal() {
		const txt = coNewGoal.trim();
		if (!txt) return;
		const maxId = coMdEdit.goals.reduce((m, g) => Math.max(m, g.id), 0);
		coMdEdit = { ...coMdEdit, goals: [...coMdEdit.goals, { id: maxId + 1, text: txt, done: false }] };
		coNewGoal = '';
	}
	function coRemoveGoal(id: number) {
		coMdEdit = { ...coMdEdit, goals: coMdEdit.goals.filter(g => g.id !== id) };
	}

	const canManageCompany = $derived(can('dept_head'));

	const ROLE_WEIGHT: Record<string, number> = {
		founder: 5, executive: 4, dept_head: 3, agent_owner: 2, user: 1,
	};
	const userRole   = $derived(currentUser?.companies.find(c => c.company_id === active?.id)?.role ?? 'user');
	const roleWeight = $derived(ROLE_WEIGHT[userRole] ?? 1);
	function can(minRole: string): boolean { return roleWeight >= (ROLE_WEIGHT[minRole] ?? 1); }
</script>

{#if isPublicPage}
	{@render children()}
{:else}
<div class="min-h-screen bg-background">

	<!-- ── Top Navigation ────────────────────────────────────────────────────── -->
	<div class="relative z-30 border-b bg-card">
		<div class="max-w-screen-2xl mx-auto">
			<div class="flex items-center justify-between px-6 h-14">

				<!-- Left: Hamburger (mobile) + Logo -->
				<div class="flex items-center gap-x-3">
					<Button variant="ghost" size="icon" class="lg:hidden"
						onclick={() => (sidebarOpen = !sidebarOpen)} aria-label="Menüyü aç">
						<Menu class="w-5 h-5" />
					</Button>
					<div class="flex items-center gap-x-2.5">
						<div class="w-10 h-10 bg-primary rounded-xl flex items-center justify-center">
							<Layers class="w-5 h-5 text-primary-foreground" />
						</div>
						<div class="flex items-baseline">
							<span class="font-bold text-xl tracking-tighter">fab</span>
							<span class="font-semibold text-xl tracking-tighter text-muted-foreground">.engineering</span>
						</div>
					</div>
				</div>

				<!-- Right: Company picker + Lang + User -->
				<div class="flex items-center gap-x-1">

					<!-- Company dropdown -->
					<div class="relative">
						<Button variant="ghost" size="sm" class="gap-x-1.5 px-2.5 text-sm max-w-[180px]"
							onclick={() => { companyMenuOpen = !companyMenuOpen; langMenuOpen = false; }}>
							{#if active}
								<Building2 class="w-4 h-4 text-muted-foreground flex-shrink-0" />
								<span class="truncate font-medium">{active.name}</span>
								{#if a2aPendingCount > 0}
									<span class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse flex-shrink-0"></span>
								{/if}
							{:else}
								<Building2 class="w-4 h-4 text-muted-foreground" />
								<span class="text-muted-foreground">Şirket seç</span>
							{/if}
							<ChevronDown class="w-3.5 h-3.5 text-muted-foreground flex-shrink-0 {companyMenuOpen ? 'rotate-180' : ''} transition-transform" />
						</Button>

						{#if companyMenuOpen}
							<div class="absolute right-0 top-full mt-1 w-64 bg-card border border-border rounded-xl shadow-lg z-50 py-1 overflow-hidden">
								{#each companyList as c}
									<button class="w-full flex items-start gap-x-2.5 px-3 py-2.5 text-sm hover:bg-muted/60 transition-colors text-left {c.id === active?.id ? 'bg-muted/40' : ''}"
										onclick={() => selectCompany(c)}>
										<Building2 class="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" />
										<div class="min-w-0 flex-1">
											<div class="font-medium truncate">{c.name}</div>
											<div class="text-xs text-muted-foreground">{c.stats.departments} dept · {c.stats.agents} agents</div>
										</div>
										{#if c.id === active?.id}
											<Check class="w-3.5 h-3.5 text-primary flex-shrink-0 mt-0.5" />
										{/if}
									</button>
								{/each}
								<div class="border-t border-border/50 mt-1 pt-1">
									{#if !addingCompany}
										<button class="w-full flex items-center gap-x-2.5 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
											onclick={(e) => { e.stopPropagation(); addingCompany = true; }}>
											<Plus class="w-4 h-4" /><span>{t('company_add')}</span>
										</button>
									{:else}
										<div class="px-3 py-2" onclick={(e) => e.stopPropagation()}>
											<input type="text"
												class="w-full text-sm bg-background border border-border rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground"
												placeholder={t('company_add_placeholder')}
												bind:value={newCompanyName}
												onkeydown={(e) => { if (e.key === 'Enter') handleAddCompany(); if (e.key === 'Escape') { addingCompany = false; newCompanyName = ''; } }}
												autofocus />
											{#if addError}<p class="text-xs text-destructive mt-1">{addError}</p>{/if}
											<div class="flex gap-x-2 mt-2">
												<Button size="sm" class="flex-1 h-7 text-xs" onclick={handleAddCompany}
													disabled={adding || !newCompanyName.trim()}>
													{adding ? '...' : t('company_add_confirm')}
												</Button>
												<Button variant="ghost" size="sm" class="flex-1 h-7 text-xs"
													onclick={() => { addingCompany = false; newCompanyName = ''; addError = ''; }}>
													{t('company_add_cancel')}
												</Button>
											</div>
										</div>
									{/if}
								</div>
							</div>
						{/if}
					</div>

					<!-- Company.md gear icon -->
					{#if active}
						<Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground"
							onclick={openCoMd} title="Şirket bilgileri">
							<Settings2 class="w-4 h-4" />
						</Button>
					{/if}

					<!-- Language picker -->
					<div class="relative">
						<Button variant="ghost" size="sm" class="gap-x-1.5 px-2 text-sm"
							onclick={() => { langMenuOpen = !langMenuOpen; companyMenuOpen = false; }}>
							<Globe class="w-4 h-4 text-muted-foreground" />
							<span class="hidden sm:inline font-medium">{currentLang.flag} {currentLang.code.toUpperCase()}</span>
							<ChevronDown class="w-3.5 h-3.5 text-muted-foreground" />
						</Button>
						{#if langMenuOpen}
							<div class="absolute right-0 top-full mt-1 w-40 bg-card border border-border rounded-xl shadow-lg z-50 py-1 overflow-hidden">
								{#each locales as loc}
									<button class="w-full flex items-center gap-x-2.5 px-3 py-2 text-sm hover:bg-muted/60 transition-colors {loc.code === i18n.locale ? 'font-semibold text-primary' : 'text-foreground'}"
										onclick={() => { i18n.locale = loc.code; langMenuOpen = false; }}>
										<span class="text-base">{loc.flag}</span><span>{loc.label}</span>
										{#if loc.code === i18n.locale}<Check class="w-3.5 h-3.5 ml-auto" />{/if}
									</button>
								{/each}
							</div>
						{/if}
					</div>

					<!-- User -->
					<a href="/profile">
						<Button variant="ghost" size="sm" class="gap-x-2 px-2">
							<div class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center ring-1 ring-border text-xs font-bold text-primary">
								{userInitials}
							</div>
							<span class="hidden sm:block text-sm font-medium">{currentUser?.name ?? 'Kullanıcı'}</span>
						</Button>
					</a>
					<Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground"
						onclick={logout} title="Çıkış Yap">
						<LogOut class="w-4 h-4" />
					</Button>
				</div>
			</div>
		</div>
	</div>

	<div class="max-w-screen-2xl mx-auto flex relative">

		<!-- Click-outside overlay for dropdowns -->
		{#if companyMenuOpen || langMenuOpen}
			<div class="fixed inset-0 z-20"
				onclick={() => { companyMenuOpen = false; langMenuOpen = false; addingCompany = false; }}
				aria-hidden="true"></div>
		{/if}

		<!-- Mobile backdrop -->
		{#if sidebarOpen}
			<div class="fixed inset-0 z-30 bg-black/50 lg:hidden"
				onclick={() => (sidebarOpen = false)} aria-hidden="true"></div>
		{/if}

		<!-- ── Sidebar ──────────────────────────────────────────────────────────── -->
		<aside class={[
			'border-r bg-card z-40 overflow-y-auto flex flex-col',
			'fixed inset-y-0 left-0 w-72 transition-all duration-200 ease-in-out',
			'lg:static lg:inset-y-auto lg:left-auto lg:min-h-[calc(100vh-3.5rem)]',
			sidebarCollapsed ? 'lg:w-16' : 'lg:w-60',
			sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
		].join(' ')}>

			<!-- Mobile header -->
			<div class="flex items-center justify-between px-4 h-14 border-b lg:hidden flex-shrink-0">
				<div class="flex items-center gap-x-2">
					<div class="w-9 h-9 bg-primary rounded-lg flex items-center justify-center">
						<Layers class="w-5 h-5 text-primary-foreground" />
					</div>
					<div class="flex items-baseline">
						<span class="font-bold tracking-tight">fab</span>
						<span class="font-semibold tracking-tight text-muted-foreground">.engineering</span>
					</div>
				</div>
				<Button variant="ghost" size="icon" onclick={() => (sidebarOpen = false)} aria-label="Menüyü kapat">
					<X class="w-5 h-5" />
				</Button>
			</div>

			<!-- Nav items -->
			<nav class="flex-1 p-3 flex flex-col gap-y-1 pt-4">

				{#if can('dept_head')}
					<a href="/">
						<Button variant={$page.url.pathname === '/' ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
							<Cpu class="w-4 h-4 flex-shrink-0" />
							{#if !sidebarCollapsed}<span class="truncate">{t('nav_structure')}</span>{/if}
						</Button>
					</a>
				{/if}

				{#if can('dept_head')}
					<a href="/departments">
						<Button variant={$page.url.pathname.startsWith('/departments') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
							<Building class="w-4 h-4 flex-shrink-0" />
							{#if !sidebarCollapsed}<span class="truncate">{t('nav_departments')}</span>{/if}
						</Button>
					</a>
				{/if}

				{#if can('dept_head')}
					<a href="/personnel">
						<Button variant={$page.url.pathname.startsWith('/personnel') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
							<UserRound class="w-4 h-4 flex-shrink-0" />
							{#if !sidebarCollapsed}<span class="truncate">{t('nav_personnel')}</span>{/if}
						</Button>
					</a>
				{/if}

				{#if can('agent_owner')}
					<a href="/agents">
						<Button variant={$page.url.pathname.startsWith('/agents') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
							<Bot class="w-4 h-4 flex-shrink-0" />
							{#if !sidebarCollapsed}<span class="truncate">{t('nav_agents')}</span>{/if}
						</Button>
					</a>
				{/if}

				{#if can('dept_head')}
					<a href="/org-chart">
						<Button variant={$page.url.pathname.startsWith('/org-chart') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
							<GitBranch class="w-4 h-4 flex-shrink-0" />
							{#if !sidebarCollapsed}<span class="truncate">{t('nav_org_chart')}</span>{/if}
						</Button>
					</a>
				{/if}

				{#if can('dept_head')}
					<a href="/change-requests">
						<Button variant={$page.url.pathname.startsWith('/change-requests') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
							<GitPullRequest class="w-4 h-4 flex-shrink-0" />
							{#if !sidebarCollapsed}<span class="truncate">{t('nav_change_requests')}</span>{/if}
						</Button>
					</a>
				{/if}

				<a href="/inbox">
					<Button variant={$page.url.pathname.startsWith('/inbox') ? 'secondary' : 'ghost'}
						class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
						<Inbox class="w-4 h-4 flex-shrink-0" />
						{#if !sidebarCollapsed}
							<span class="flex-1 truncate">{t('nav_inbox')}</span>
						{/if}
					</Button>
				</a>

				{#if can('agent_owner')}
					<a href="/flows">
						<Button variant={$page.url.pathname.startsWith('/flows') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
							<Zap class="w-4 h-4 flex-shrink-0" />
							{#if !sidebarCollapsed}<span class="truncate">{t('nav_flows')}</span>{/if}
						</Button>
					</a>
				{/if}

				<a href="/chat">
					<Button variant={$page.url.pathname.startsWith('/chat') ? 'secondary' : 'ghost'}
						class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
						<BriefcaseBusiness class="w-4 h-4 flex-shrink-0" />
						{#if !sidebarCollapsed}<span class="truncate">{t('nav_jobs')}</span>{/if}
					</Button>
				</a>

				<a href="/a2a">
					<Button variant={$page.url.pathname.startsWith('/a2a') ? 'secondary' : 'ghost'}
						class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
						<ArrowLeftRight class="w-4 h-4 flex-shrink-0" />
						{#if !sidebarCollapsed}
							<span class="flex-1 truncate">{t('nav_delegation')}</span>
							{#if a2aPendingCount > 0}
								<span class="px-1.5 py-0.5 rounded-full text-xs bg-amber-100 text-amber-700 font-semibold leading-none">
									{a2aPendingCount}
								</span>
							{/if}
						{:else if a2aPendingCount > 0}
							<span class="absolute top-1 right-1 w-2 h-2 rounded-full bg-amber-500"></span>
						{/if}
					</Button>
				</a>

				<!-- Spacer -->
				<div class="flex-1"></div>

				<!-- Settings at bottom -->
				{#if can('executive')}
					<div class="border-t border-border/50 pt-3 mt-2">
						<a href="/settings">
							<Button variant={$page.url.pathname.startsWith('/settings') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium {sidebarCollapsed ? 'lg:justify-center lg:px-0' : ''}">
								<Settings class="w-4 h-4 flex-shrink-0" />
								{#if !sidebarCollapsed}<span class="truncate">{t('nav_settings')}</span>{/if}
							</Button>
						</a>
					</div>
				{/if}

				<!-- Collapse toggle (desktop only) -->
				<div class="hidden lg:block pt-1">
					<Button variant="ghost" size="sm"
						class="w-full h-8 text-muted-foreground hover:text-foreground {sidebarCollapsed ? 'justify-center px-0' : 'justify-start gap-x-3 px-3'}"
						onclick={() => (sidebarCollapsed = !sidebarCollapsed)}>
						{#if sidebarCollapsed}
							<ChevronRight class="w-4 h-4" />
						{:else}
							<ChevronLeft class="w-4 h-4" />
							<span class="text-xs">Daralt</span>
						{/if}
					</Button>
				</div>

			</nav>
		</aside>

		<!-- ── Main Content ─────────────────────────────────────────────────────── -->
		<div class="flex-1 min-w-0 p-8">
			{@render children()}
		</div>
	</div>

	<!-- ── Company.md Side Panel ─────────────────────────────────────────────── -->
	{#if coMdOpen}
		<div class="fixed inset-0 z-30 bg-black/40 lg:hidden" onclick={() => (coMdOpen = false)} aria-hidden="true"></div>
	{/if}
	<aside class="co-md-panel {coMdOpen ? 'translate-x-0' : 'translate-x-full'}">
		<!-- Header -->
		<div class="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
			<div class="flex items-center gap-2.5">
				<div class="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
					<Building2 class="w-4 h-4 text-muted-foreground" />
				</div>
				<div>
					<div class="font-semibold text-sm">Şirket Bilgileri</div>
					<div class="text-xs text-muted-foreground">company.md</div>
				</div>
			</div>
			<Button variant="ghost" size="icon" onclick={() => (coMdOpen = false)}>
				<X class="w-4 h-4" />
			</Button>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-y-auto px-6 py-5 space-y-6">

			<!-- Identity -->
			<section class="space-y-4">
				<div class="co-section-label"><span class="co-badge">1</span>Kimlik</div>
				{#if canManageCompany}
					<div class="grid sm:grid-cols-2 gap-3">
						<div class="space-y-1.5 sm:col-span-2">
							<label class="text-sm font-medium" for="co-name">Şirket Adı</label>
							<Input id="co-name" bind:value={coMdEdit.name} placeholder="Acme Corp" />
						</div>
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="co-sector">Sektör</label>
							<Input id="co-sector" bind:value={coMdEdit.sector} placeholder="Yazılım & SaaS" />
						</div>
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="co-web">Web Sitesi</label>
							<Input id="co-web" bind:value={coMdEdit.website} placeholder="https://..." />
						</div>
					</div>
				{:else}
					<div class="space-y-1.5 text-sm">
						<div class="font-semibold text-base">{coMdEdit.name || active?.name}</div>
						{#if coMdEdit.sector}<div class="text-muted-foreground">{coMdEdit.sector}</div>{/if}
						{#if coMdEdit.website}<a href={coMdEdit.website} class="text-primary text-xs">{coMdEdit.website}</a>{/if}
					</div>
				{/if}
			</section>

			<!-- Vision & Mission -->
			<section class="space-y-4">
				<div class="co-section-label"><span class="co-badge">2</span>Vizyon & Misyon</div>
				{#if canManageCompany}
					<div class="space-y-3">
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="co-vision">Vizyon</label>
							<textarea id="co-vision" bind:value={coMdEdit.vision} class="co-textarea" rows="3" placeholder="Uzun vadeli hedef..."></textarea>
						</div>
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="co-mission">Misyon</label>
							<textarea id="co-mission" bind:value={coMdEdit.mission} class="co-textarea" rows="3" placeholder="Günlük amaç..."></textarea>
						</div>
					</div>
				{:else}
					<div class="space-y-3">
						{#if coMdEdit.vision}
							<div>
								<div class="text-xs font-semibold text-muted-foreground mb-1">VİZYON</div>
								<p class="text-sm text-muted-foreground leading-relaxed">{coMdEdit.vision}</p>
							</div>
						{/if}
						{#if coMdEdit.mission}
							<div>
								<div class="text-xs font-semibold text-muted-foreground mb-1">MİSYON</div>
								<p class="text-sm text-muted-foreground leading-relaxed">{coMdEdit.mission}</p>
							</div>
						{/if}
					</div>
				{/if}
			</section>

			<!-- Values -->
			<section class="space-y-3">
				<div class="co-section-label"><span class="co-badge">3</span>Değerler</div>
				{#if coMdEdit.values.length > 0}
					<div class="flex flex-wrap gap-2">
						{#each coMdEdit.values as val}
							<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium">
								{val}
								{#if canManageCompany}
									<button type="button" onclick={() => coRemoveValue(val)} class="hover:text-destructive transition-colors" aria-label="Kaldır">
										<X class="w-3 h-3" />
									</button>
								{/if}
							</span>
						{/each}
					</div>
				{/if}
				{#if canManageCompany}
					<div class="flex gap-2">
						<Input bind:value={coNewValue} placeholder="Yeni değer..." class="flex-1"
							onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); coAddValue(); } }} />
						<Button variant="outline" size="sm" onclick={coAddValue} disabled={!coNewValue.trim()}>
							<Plus class="w-3.5 h-3.5" />
						</Button>
					</div>
				{/if}
			</section>

			<!-- Goals -->
			<section class="space-y-3">
				<div class="co-section-label"><span class="co-badge">4</span>Hedefler</div>
				{#if coMdEdit.goals.length > 0}
					<div class="space-y-2">
						{#each coMdEdit.goals as goal}
							<div class="flex items-start gap-2 px-3 py-2 rounded-lg bg-muted/60 border border-border/50 group/g">
								<div class="w-3.5 h-3.5 rounded-sm bg-emerald-500/20 border border-emerald-500/50 flex-shrink-0 mt-0.5"></div>
								<span class="text-sm flex-1">{goal.text}</span>
								{#if canManageCompany}
									<button type="button" onclick={() => coRemoveGoal(goal.id)}
										class="text-muted-foreground hover:text-destructive transition-colors opacity-0 group-hover/g:opacity-100 flex-shrink-0"
										aria-label="Kaldır">
										<X class="w-3.5 h-3.5" />
									</button>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
				{#if canManageCompany}
					<div class="flex gap-2">
						<Input bind:value={coNewGoal} placeholder="Yeni hedef..." class="flex-1"
							onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); coAddGoal(); } }} />
						<Button variant="outline" size="sm" onclick={coAddGoal} disabled={!coNewGoal.trim()}>
							<Plus class="w-3.5 h-3.5" />
						</Button>
					</div>
				{/if}
			</section>
		</div>

		{#if canManageCompany}
			<div class="border-t px-6 py-4 flex gap-3 justify-end flex-shrink-0 bg-card">
				<Button variant="outline" onclick={() => (coMdOpen = false)}>İptal</Button>
				<Button onclick={() => (coMdOpen = false)}>Kaydet</Button>
			</div>
		{/if}
	</aside>

</div>
{/if}


<style>
.co-md-panel {
	position: fixed;
	top: 0; right: 0; bottom: 0;
	width: 520px;
	max-width: 100vw;
	background: hsl(var(--card));
	border-left: 1px solid hsl(var(--border));
	box-shadow: -8px 0 32px rgba(0,0,0,0.08);
	z-index: 40;
	display: flex;
	flex-direction: column;
	transition: transform 0.2s cubic-bezier(0.32,0.72,0,1);
}
.co-section-label {
	display: flex;
	align-items: center;
	gap: 0.5rem;
	font-size: 0.6875rem;
	font-weight: 700;
	color: hsl(var(--muted-foreground));
	text-transform: uppercase;
	letter-spacing: 0.1em;
}
.co-badge {
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
.co-textarea {
	display: flex;
	width: 100%;
	border-radius: 0.375rem;
	border: 1px solid hsl(var(--input));
	background: hsl(var(--background));
	padding: 0.5rem 0.75rem;
	font-size: 0.875rem;
	resize: vertical;
	outline: none;
	font-family: inherit;
}
.co-textarea:focus {
	box-shadow: 0 0 0 1px hsl(var(--ring));
}
</style>
