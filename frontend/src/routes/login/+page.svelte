<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { Layers, Mail, Lock, Loader, Building2, Globe, Check, KeyRound } from '@lucide/svelte';
	import Button from '$lib/components/ui/button.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { companyStore } from '$lib/stores/company.svelte';
	import { tenantStore } from '$lib/stores/tenant.svelte';
	import { i18n, type Locale } from '$lib/i18n/index.svelte';

	let email = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);
	let langMenuOpen = $state(false);

	// OTP flow (demo subdomain)
	let isDemo = $state(false);
	let otpStep = $state<'email' | 'code'>('email');
	let otpCode = $state('');
	let otpSent = $state(false);
	let devCode = $state(''); // shown when SMTP not configured

	const locales: { code: Locale; label: string; flag: string }[] = [
		{ code: 'tr', label: 'Türkçe', flag: '🇹🇷' },
		{ code: 'en', label: 'English', flag: '🇬🇧' }
	];

	onMount(async () => {
		await tenantStore.resolve();
		const host = typeof window !== 'undefined' ? window.location.hostname : '';
		isDemo = host.startsWith('demo.');
	});

	// ── Normal password login ──────────────────────────────────────────────────

	async function submit(e: Event) {
		e.preventDefault();
		if (!email.trim() || !password) return;
		loading = true;
		error = '';
		try {
			const user = await authStore.login(email.trim().toLowerCase(), password);
			await companyStore.load();

			if (tenantStore.slug) {
				const match = companyStore.list.find((c) => c.slug === tenantStore.slug);
				if (match) companyStore.setActive(match);
			}

			if (user.must_change_password) {
				goto('/set-password?mode=first');
				return;
			}
			const firstCompany = user.companies[0];
			const role = firstCompany?.role;
			if (role === 'agent_owner') goto('/agents');
			else if (role === 'user') goto('/inbox');
			else goto('/');
		} catch (e: any) {
			error = e?.message ?? i18n.t('login_error_default');
		} finally {
			loading = false;
		}
	}

	// ── OTP demo login ─────────────────────────────────────────────────────────

	async function requestOtp(e: Event) {
		e.preventDefault();
		if (!email.trim()) return;
		loading = true;
		error = '';
		devCode = '';
		try {
			const res = await fetch('/auth/demo/request-otp', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email: email.trim().toLowerCase() })
			});
			const data = await res.json();
			if (!res.ok) throw new Error(data.detail ?? i18n.t('demo_req_failed'));
			otpSent = true;
			otpStep = 'code';
			if (data.code) devCode = data.code; // dev fallback
		} catch (e: any) {
			error = e?.message;
		} finally {
			loading = false;
		}
	}

	async function verifyOtp(e: Event) {
		e.preventDefault();
		if (!otpCode.trim()) return;
		loading = true;
		error = '';
		try {
			const res = await fetch('/auth/demo/verify-otp', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email: email.trim().toLowerCase(), code: otpCode.trim() })
			});
			const data = await res.json();
			if (!res.ok) throw new Error(data.detail ?? i18n.t('demo_verify_failed'));

			// Store token and fetch /auth/me
			await authStore.loginWithToken(data.access_token);
			await companyStore.load();

			const match = companyStore.list.find((c) => c.slug === 'demo');
			if (match) companyStore.setActive(match);

			goto('/');
		} catch (e: any) {
			error = e?.message;
		} finally {
			loading = false;
		}
	}

	const tenant = $derived(tenantStore.info);
	const currentLang = $derived(locales.find((l) => l.code === i18n.locale)!);
</script>

<svelte:head>
	<title>{tenant?.name ? `${tenant.name} — ${i18n.t('login_title')}` : `${i18n.t('login_title')} • fab.engineering`}</title>
</svelte:head>

<div class="min-h-screen bg-background flex items-center justify-center p-4">
	<!-- Language switcher -->
	<div class="absolute top-4 right-4">
		<div class="relative">
			<button
				class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors border border-border/50"
				onclick={() => (langMenuOpen = !langMenuOpen)}
			>
				<Globe class="w-3.5 h-3.5" />
				<span>{currentLang.flag} {currentLang.label}</span>
			</button>
			{#if langMenuOpen}
				<div class="absolute right-0 top-full mt-1 w-36 rounded-xl border bg-card shadow-lg overflow-hidden z-50">
					{#each locales as loc}
						<button
							class="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-muted/60 transition-colors {loc.code === i18n.locale ? 'font-semibold text-primary' : 'text-foreground'}"
							onclick={() => { i18n.locale = loc.code; langMenuOpen = false; }}
						>
							<span>{loc.flag}</span>
							<span>{loc.label}</span>
							{#if loc.code === i18n.locale}<Check class="w-3.5 h-3.5 ml-auto" />{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</div>

	{#if langMenuOpen}
		<div class="fixed inset-0 z-40" onclick={() => (langMenuOpen = false)}></div>
	{/if}

	<div class="w-full max-w-sm">
		<!-- Logo / Tenant branding -->
		<div class="flex items-center justify-center gap-2.5 mb-8">
			{#if tenant?.name}
				<div class="w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center">
					<Building2 class="w-6 h-6 text-primary" />
				</div>
				<div class="flex flex-col">
					<span class="font-bold text-xl tracking-tight">{tenant.name}</span>
					<span class="text-xs text-muted-foreground">agent.fab.engineering</span>
				</div>
			{:else}
				<div class="w-12 h-12 bg-primary rounded-xl flex items-center justify-center">
					<Layers class="w-6 h-6 text-primary-foreground" />
				</div>
				<div class="flex items-baseline">
					<span class="font-bold text-2xl tracking-tighter">fab</span>
					<span class="font-semibold text-2xl tracking-tighter text-muted-foreground">.engineering</span>
				</div>
			{/if}
		</div>

		<!-- Card -->
		<div class="rounded-2xl border bg-card p-8 shadow-sm">

			{#if isDemo}
				<!-- ── Demo OTP flow ─────────────────────────────────────────── -->
				{#if otpStep === 'email'}
					<div class="flex items-center gap-2 mb-1 justify-center">
						<KeyRound class="w-5 h-5 text-primary" />
						<h1 class="font-display text-xl tracking-tight">{i18n.t('demo_title')}</h1>
					</div>
					<p class="text-sm text-muted-foreground text-center mb-6">
						{i18n.t('demo_subtitle')}
					</p>

					<form onsubmit={requestOtp} class="space-y-4">
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="demo-email">{i18n.t('login_email')}</label>
							<div class="relative">
								<Mail class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
								<Input
									id="demo-email"
									type="email"
									bind:value={email}
									placeholder={i18n.t('demo_email_ph')}
									class="pl-9"
									autocomplete="email"
									required
								/>
							</div>
						</div>

						{#if error}
							<div class="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5 text-sm text-destructive">
								{error}
							</div>
						{/if}

						<Button type="submit" class="w-full" disabled={loading || !email}>
							{#if loading}
								<Loader class="w-4 h-4 animate-spin" />
								{i18n.t('demo_sending')}
							{:else}
								{i18n.t('demo_send_code')}
							{/if}
						</Button>
					</form>
				{:else}
					<!-- code step -->
					<div class="flex items-center gap-2 mb-1 justify-center">
						<KeyRound class="w-5 h-5 text-primary" />
						<h1 class="font-display text-xl tracking-tight">{i18n.t('demo_verify_title')}</h1>
					</div>
					<p class="text-sm text-muted-foreground text-center mb-6">
						{i18n.t('demo_code_sent_pre')}<span class="font-medium text-foreground">{email}</span>{i18n.t('demo_code_sent_suf')}
						{i18n.t('demo_code_valid')}
					</p>

					{#if devCode}
						<div class="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2.5 text-sm text-amber-800 mb-4 text-center">
							<span class="font-medium">{i18n.t('demo_test_code')}</span>
							<span class="font-mono text-lg tracking-widest ml-2">{devCode}</span>
						</div>
					{/if}

					<form onsubmit={verifyOtp} class="space-y-4">
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="otp-code">{i18n.t('demo_code_label')}</label>
							<Input
								id="otp-code"
								type="text"
								inputmode="numeric"
								pattern="[0-9]*"
								maxlength={6}
								bind:value={otpCode}
								placeholder="000000"
								class="text-center text-2xl tracking-widest font-mono"
								autocomplete="one-time-code"
								required
							/>
						</div>

						{#if error}
							<div class="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5 text-sm text-destructive">
								{error}
							</div>
						{/if}

						<Button type="submit" class="w-full" disabled={loading || otpCode.length < 6}>
							{#if loading}
								<Loader class="w-4 h-4 animate-spin" />
								{i18n.t('demo_verifying')}
							{:else}
								{i18n.t('login_submit')}
							{/if}
						</Button>

						<button
							type="button"
							class="w-full text-xs text-muted-foreground hover:text-foreground transition-colors"
							onclick={() => { otpStep = 'email'; otpCode = ''; error = ''; devCode = ''; }}
						>
							{i18n.t('demo_change_email')}
						</button>
					</form>
				{/if}

			{:else}
				<!-- ── Normal password login ──────────────────────────────────── -->
				<h1 class="font-display text-xl tracking-tight text-center mb-1">{i18n.t('login_title')}</h1>
				<p class="text-sm text-muted-foreground text-center mb-6">
					{tenant?.name
						? `${tenant.name} ${i18n.t('login_tenant_subtitle')}`
						: i18n.t('login_subtitle')}
				</p>

				<form onsubmit={submit} class="space-y-4">
					<div class="space-y-1.5">
						<label class="text-sm font-medium" for="email">{i18n.t('login_email')}</label>
						<div class="relative">
							<Mail class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
							<Input
								id="email"
								type="email"
								bind:value={email}
								placeholder={i18n.t('login_email_placeholder')}
								class="pl-9"
								autocomplete="email"
								required
							/>
						</div>
					</div>

					<div class="space-y-1.5">
						<label class="text-sm font-medium" for="password">{i18n.t('login_password')}</label>
						<div class="relative">
							<Lock class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
							<Input
								id="password"
								type="password"
								bind:value={password}
								placeholder="••••••••"
								class="pl-9"
								autocomplete="current-password"
								required
							/>
						</div>
					</div>

					{#if error}
						<div class="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5 text-sm text-destructive">
							{error}
						</div>
					{/if}

					<Button type="submit" class="w-full" disabled={loading || !email || !password}>
						{#if loading}
							<Loader class="w-4 h-4 animate-spin" />
							{i18n.t('login_submitting')}
						{:else}
							{i18n.t('login_submit')}
						{/if}
					</Button>
				</form>

				<div class="mt-5 pt-4 border-t text-center">
					<a href="/request-reset" class="text-xs text-muted-foreground hover:text-foreground transition-colors">
						{i18n.t('login_forgot')}
					</a>
				</div>
			{/if}
		</div>

		{#if tenant?.name}
			<p class="text-center text-xs text-muted-foreground mt-4">
				{i18n.t('login_powered_by')} <a href="https://fab.engineering" class="hover:text-foreground transition-colors">fab.engineering</a>
			</p>
		{/if}
	</div>
</div>
