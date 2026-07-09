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
	} from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { companyStore } from '$lib/stores/company.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { i18n, type Locale } from '$lib/i18n/index.svelte';
	import type { Company } from '$lib/api/companies';
	import { a2aApi } from '$lib/api/a2a';

	let { children }: { children: Snippet } = $props();

	// Public routes — no auth required
	const PUBLIC_ROUTES = ['/login', '/set-password', '/request-reset', '/setup'];

	let sidebarOpen = $state(false);
	let companyMenuOpen = $state(false);
	let langMenuOpen = $state(false);
	let addingCompany = $state(false);
	let newCompanyName = $state('');
	let addError = $state('');
	let adding = $state(false);
	let a2aPendingCount = $state(0);

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
	});

	onMount(() => {
		(async () => {
			// Check first-time setup before anything else
			try {
				const { API_URL } = await import('$lib/api/client');
				const res = await fetch(`${API_URL}/auth/setup-status`);
				if (res.ok) {
					const { needs_setup } = await res.json();
					if (needs_setup && $page.url.pathname !== '/setup') {
						goto('/setup');
						return;
					}
				}
			} catch {}

			await authStore.init();
			const path = $page.url.pathname;
			const isPublic = PUBLIC_ROUTES.some(r => path.startsWith(r));
			if (!authStore.isLoggedIn && !isPublic) {
				goto('/login');
				return;
			}
			if (authStore.isLoggedIn && authStore.user?.must_change_password && path !== '/set-password') {
				goto('/set-password');
				return;
			}
			if (authStore.isLoggedIn) {
				await loadCompanies();
			}
		})();
		const timer = setInterval(loadA2ACount, 30000);
		return () => clearInterval(timer);
	});

	// Re-runs when auth state changes — handles post-setup / post-login navigation
	$effect(() => {
		if (authStore.isLoggedIn && !companyStore.loaded) {
			loadCompanies();
		}
	});

	$effect(() => {
		if (companyStore.active) loadA2ACount();
	});

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
		adding = true;
		addError = '';
		try {
			await companyStore.create(newCompanyName.trim());
			newCompanyName = '';
			addingCompany = false;
			companyMenuOpen = false;
		} catch (e: any) {
			addError = e?.message ?? 'Hata oluştu';
		} finally {
			adding = false;
		}
	}

	function selectCompany(c: Company) {
		companyStore.setActive(c);
		companyMenuOpen = false;
	}

	const currentLang = $derived(locales.find(l => l.code === i18n.locale)!);
	const active = $derived(companyStore.active);
	const companyList = $derived(companyStore.list);
	const currentUser = $derived(authStore.user);
	const userInitials = $derived(
		currentUser?.name
			?.split(' ')
			.map(w => w[0])
			.slice(0, 2)
			.join('')
			.toUpperCase() ?? '??'
	);

	function logout() {
		authStore.logout();
		goto('/login');
	}

	const isPublicPage = $derived(
		PUBLIC_ROUTES.some(r => $page.url.pathname.startsWith(r))
	);

	// ── Role-based nav ────────────────────────────────────────────────────────
	// Weight: founder=5 executive=4 dept_head=3 agent_owner=2 user=1
	const ROLE_WEIGHT: Record<string, number> = {
		founder: 5, executive: 4, dept_head: 3, agent_owner: 2, user: 1,
	};

	const userRole = $derived(
		currentUser?.companies.find(c => c.company_id === active?.id)?.role ?? 'user'
	);
	const roleWeight = $derived(ROLE_WEIGHT[userRole] ?? 1);

	// Returns true if user's role weight >= required weight
	function can(minRole: string): boolean {
		return roleWeight >= (ROLE_WEIGHT[minRole] ?? 1);
	}
</script>

{#if isPublicPage}
	{@render children()}
{:else}
<div class="min-h-screen bg-background">
	<!-- Top Navigation -->
	<div class="relative z-30 border-b bg-card">
		<div class="max-w-screen-2xl mx-auto">
			<div class="flex items-center justify-between px-6 h-14">
				<!-- Left: Hamburger (mobile) + Logo -->
				<div class="flex items-center gap-x-3">
					<Button
						variant="ghost"
						size="icon"
						class="lg:hidden"
						onclick={() => (sidebarOpen = !sidebarOpen)}
						aria-label="Menüyü aç"
					>
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

				<!-- Right: Active company badge + Lang picker + User -->
				<div class="flex items-center gap-x-2">
					{#if active}
						<div class="hidden sm:flex items-center gap-x-2 px-3 py-1.5 rounded-full bg-muted/50 text-sm">
							<div class="w-2 h-2 bg-emerald-500 rounded-full"></div>
							<span class="text-muted-foreground font-medium">{active.name}</span>
						</div>
					{/if}

					<!-- Language picker -->
					<div class="relative">
						<Button
							variant="ghost"
							size="sm"
							class="gap-x-1.5 px-2 text-sm"
							onclick={() => { langMenuOpen = !langMenuOpen; companyMenuOpen = false; }}
						>
							<Globe class="w-4 h-4 text-muted-foreground" />
							<span class="hidden sm:inline font-medium">{currentLang.flag} {currentLang.code.toUpperCase()}</span>
							<ChevronDown class="w-3.5 h-3.5 text-muted-foreground" />
						</Button>

						{#if langMenuOpen}
							<div class="absolute right-0 top-full mt-1 w-40 bg-card border border-border rounded-xl shadow-lg z-50 py-1 overflow-hidden">
								{#each locales as loc}
									<button
										class="w-full flex items-center gap-x-2.5 px-3 py-2 text-sm hover:bg-muted/60 transition-colors {loc.code === i18n.locale ? 'font-semibold text-primary' : 'text-foreground'}"
										onclick={() => { i18n.locale = loc.code; langMenuOpen = false; }}
									>
										<span class="text-base">{loc.flag}</span>
										<span>{loc.label}</span>
										{#if loc.code === i18n.locale}
											<Check class="w-3.5 h-3.5 ml-auto" />
										{/if}
									</button>
								{/each}
							</div>
						{/if}
					</div>

					<div class="flex items-center gap-x-1">
						<a href="/profile">
							<Button variant="ghost" size="sm" class="gap-x-2 px-2">
								<div class="flex items-center gap-x-2">
									<div class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center ring-1 ring-border text-xs font-bold text-primary">
										{userInitials}
									</div>
									<span class="hidden sm:block text-sm font-medium">{currentUser?.name ?? 'Kullanıcı'}</span>
								</div>
							</Button>
						</a>
						<Button variant="ghost" size="icon" class="h-8 w-8 text-muted-foreground hover:text-foreground" onclick={logout} title="Çıkış Yap">
							<LogOut class="w-4 h-4" />
						</Button>
					</div>
				</div>
			</div>
		</div>
	</div>

	<div class="max-w-screen-2xl mx-auto flex relative">
		<!-- Mobile backdrop -->
		{#if sidebarOpen}
			<div
				class="fixed inset-0 z-30 bg-black/50 lg:hidden"
				onclick={() => (sidebarOpen = false)}
				aria-hidden="true"
			></div>
		{/if}

		<!-- Click-outside overlay for dropdowns -->
		{#if companyMenuOpen || langMenuOpen}
			<div
				class="fixed inset-0 z-20"
				onclick={() => { companyMenuOpen = false; langMenuOpen = false; addingCompany = false; }}
				aria-hidden="true"
			></div>
		{/if}

		<!-- Sidebar -->
		<aside
			class={[
				'border-r bg-card z-40 overflow-y-auto',
				'fixed inset-y-0 left-0 w-72 transition-transform duration-200 ease-in-out',
				'lg:static lg:inset-y-auto lg:left-auto lg:w-60 lg:min-h-[calc(100vh-3.5rem)] lg:translate-x-0',
				sidebarOpen ? 'translate-x-0' : '-translate-x-full'
			].join(' ')}
		>
			<!-- Mobile header -->
			<div class="flex items-center justify-between px-4 h-14 border-b lg:hidden">
				<div class="flex items-center gap-x-2">
					<div class="w-9 h-9 bg-primary rounded-lg flex items-center justify-center">
						<Layers class="w-5 h-5 text-primary-foreground" />
					</div>
					<div class="flex items-baseline">
						<span class="font-bold tracking-tight">fab</span>
						<span class="font-semibold tracking-tight text-muted-foreground">.engineering</span>
					</div>
				</div>
				<Button
					variant="ghost"
					size="icon"
					onclick={() => (sidebarOpen = false)}
					aria-label="Menüyü kapat"
				>
					<X class="w-5 h-5" />
				</Button>
			</div>

			<!-- Nav items -->
			<div class="p-3">
				<div class="space-y-0.5 px-1 pt-2">
					{#if can('dept_head')}
						<a href="/">
							<Button
								variant={$page.url.pathname === '/' ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<Cpu class="w-4 h-4" />
								<span>{t('nav_structure')}</span>
							</Button>
						</a>
					{/if}

					{#if can('dept_head')}
						<a href="/departments">
							<Button
								variant={$page.url.pathname.startsWith('/departments') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<Building class="w-4 h-4" />
								<span>{t('nav_departments')}</span>
							</Button>
						</a>
					{/if}

					{#if can('dept_head')}
						<a href="/personnel">
							<Button
								variant={$page.url.pathname.startsWith('/personnel') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<UserRound class="w-4 h-4" />
								<span>{t('nav_personnel')}</span>
							</Button>
						</a>
					{/if}

					{#if can('agent_owner')}
						<a href="/agents">
							<Button
								variant={$page.url.pathname.startsWith('/agents') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<Bot class="w-4 h-4" />
								<span>{t('nav_agents')}</span>
							</Button>
						</a>
					{/if}

					{#if can('dept_head')}
						<a href="/org-chart">
							<Button
								variant={$page.url.pathname.startsWith('/org-chart') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<GitBranch class="w-4 h-4" />
								<span>{t('nav_org_chart')}</span>
							</Button>
						</a>
					{/if}

					{#if can('dept_head')}
						<a href="/change-requests">
							<Button
								variant={$page.url.pathname.startsWith('/change-requests') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<GitPullRequest class="w-4 h-4" />
								<span>{t('nav_change_requests')}</span>
							</Button>
						</a>
					{/if}

					<a href="/inbox">
						<Button
							variant={$page.url.pathname.startsWith('/inbox') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
						>
							<Inbox class="w-4 h-4" />
							<span>{t('nav_inbox')}</span>
						</Button>
					</a>

					{#if can('agent_owner')}
						<a href="/flows">
							<Button
								variant={$page.url.pathname.startsWith('/flows') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<Zap class="w-4 h-4" />
								<span>{t('nav_flows')}</span>
							</Button>
						</a>
					{/if}

					<a href="/chat">
						<Button
							variant={$page.url.pathname.startsWith('/chat') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
						>
							<BriefcaseBusiness class="w-4 h-4" />
							<span>{t('nav_jobs')}</span>
						</Button>
					</a>

					<a href="/a2a">
						<Button
							variant={$page.url.pathname.startsWith('/a2a') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
						>
							<ArrowLeftRight class="w-4 h-4" />
							<span class="flex-1">{t('nav_delegation')}</span>
							{#if a2aPendingCount > 0}
								<span class="px-1.5 py-0.5 rounded-full text-xs bg-amber-100 text-amber-700 font-semibold leading-none">
									{a2aPendingCount}
								</span>
							{/if}
						</Button>
					</a>
				</div>

				<!-- Settings — executive+ only -->
				{#if can('executive')}
					<div class="mt-4 pt-4 border-t border-border/50 space-y-0.5 px-1">
						<a href="/settings">
							<Button
								variant={$page.url.pathname.startsWith('/settings') ? 'secondary' : 'ghost'}
								class="w-full justify-start gap-x-3 h-9 rounded-xl text-sm font-medium"
							>
								<Settings class="w-4 h-4" />
								<span>{t('nav_settings')}</span>
							</Button>
						</a>
					</div>
				{/if}

				<!-- Company section -->
				<div class="mt-6 px-1 relative z-50">
					<div class="text-[10px] font-semibold text-muted-foreground tracking-[1.5px] mb-2 px-2">
						{t('companies_label').toUpperCase()}
					</div>

					<!-- Active company card + dropdown trigger -->
					<button
						class="w-full px-3 py-3 bg-muted/60 rounded-2xl text-sm border border-border/50 hover:border-border transition-colors text-left"
						onclick={(e) => { e.stopPropagation(); companyMenuOpen = !companyMenuOpen; langMenuOpen = false; }}
					>
						{#if active}
							<div class="flex items-center justify-between">
								<div class="min-w-0 flex-1">
									<div class="flex items-center gap-1.5">
										<span class="font-semibold truncate">{active.name}</span>
										{#if a2aPendingCount > 0}
											<span class="flex-shrink-0 w-2 h-2 rounded-full bg-amber-500 animate-pulse" title="{a2aPendingCount} bekleyen delegasyon"></span>
										{/if}
									</div>
									<div class="text-xs text-muted-foreground mt-0.5">
										{active.stats.departments} {t('company_departments')} · {active.stats.personnel} {t('company_personnel')} · {active.stats.agents} {t('company_agents')}
									</div>
								</div>
								<ChevronDown class="w-4 h-4 text-muted-foreground flex-shrink-0 ml-2 {companyMenuOpen ? 'rotate-180' : ''} transition-transform" />
							</div>
						{:else}
							<div class="text-muted-foreground text-xs">{t('loading')}</div>
						{/if}
					</button>

					<!-- Company dropdown -->
					{#if companyMenuOpen}
						<div class="absolute left-0 right-0 top-full mt-1 bg-card border border-border rounded-xl shadow-lg z-50 py-1 overflow-hidden">
							{#each companyList as c}
								<button
									class="w-full flex items-start gap-x-2.5 px-3 py-2.5 text-sm hover:bg-muted/60 transition-colors text-left {c.id === active?.id ? 'bg-muted/40' : ''}"
									onclick={() => selectCompany(c)}
								>
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
									<button
										class="w-full flex items-center gap-x-2.5 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
										onclick={(e) => { e.stopPropagation(); addingCompany = true; }}
									>
										<Plus class="w-4 h-4" />
										<span>{t('company_add')}</span>
									</button>
								{:else}
									<div class="px-3 py-2" onclick={(e) => e.stopPropagation()}>
										<input
											type="text"
											class="w-full text-sm bg-background border border-border rounded-lg px-2.5 py-1.5 outline-none focus:ring-1 focus:ring-primary/50 placeholder:text-muted-foreground"
											placeholder={t('company_add_placeholder')}
											bind:value={newCompanyName}
											onkeydown={(e) => { if (e.key === 'Enter') handleAddCompany(); if (e.key === 'Escape') { addingCompany = false; newCompanyName = ''; } }}
											autofocus
										/>
										{#if addError}
											<p class="text-xs text-destructive mt-1">{addError}</p>
										{/if}
										<div class="flex gap-x-2 mt-2">
											<Button
												size="sm"
												class="flex-1 h-7 text-xs"
												onclick={handleAddCompany}
												disabled={adding || !newCompanyName.trim()}
											>
												{adding ? '...' : t('company_add_confirm')}
											</Button>
											<Button
												variant="ghost"
												size="sm"
												class="flex-1 h-7 text-xs"
												onclick={() => { addingCompany = false; newCompanyName = ''; addError = ''; }}
											>
												{t('company_add_cancel')}
											</Button>
										</div>
									</div>
								{/if}
							</div>
						</div>
					{/if}
				</div>
			</div>
		</aside>

		<!-- Main Content -->
		<div class="flex-1 min-w-0 p-8">
			{@render children()}
		</div>
	</div>
</div>
{/if}
