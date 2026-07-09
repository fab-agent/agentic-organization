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
	} from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { companyStore } from '$lib/stores/company.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { i18n, type Locale } from '$lib/i18n/index.svelte';
	import type { Company } from '$lib/api/companies';
	import { a2aApi } from '$lib/api/a2a';

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
</div>
{/if}
