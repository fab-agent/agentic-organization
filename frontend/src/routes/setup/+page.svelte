<script lang="ts">
	import { goto } from '$app/navigation';
	import { Layers, User, Mail, Lock, Building2, Loader, Globe, Check } from '@lucide/svelte';
	import Button from '$lib/components/ui/button.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { i18n, type Locale } from '$lib/i18n/index.svelte';

	const API = import.meta.env.VITE_API_URL ?? '';

	let name = $state('');
	let email = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let companyName = $state('');
	let error = $state('');
	let loading = $state(false);
	let langMenuOpen = $state(false);

	const locales: { code: Locale; label: string; flag: string }[] = [
		{ code: 'tr', label: 'Türkçe', flag: '🇹🇷' },
		{ code: 'en', label: 'English', flag: '🇬🇧' }
	];

	const currentLang = $derived(locales.find((l) => l.code === i18n.locale)!);

	async function submit(e: Event) {
		e.preventDefault();
		error = '';

		if (password !== confirmPassword) {
			error = i18n.t('setup_error_mismatch');
			return;
		}
		if (password.length < 8) {
			error = i18n.t('setup_error_short');
			return;
		}

		loading = true;
		try {
			const res = await fetch(`${API}/auth/setup`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ name, email, password, company_name: companyName }),
			});
			const data = await res.json();
			if (!res.ok) throw new Error(data.detail ?? i18n.t('setup_error_default'));

			await authStore.login(email, password);

			// On cloud deployment: redirect to company subdomain
			const host = window.location.hostname;
			const cloudDomain = 'agent.fab.engineering';
			if (host.endsWith(cloudDomain) && data.company_slug) {
				window.location.href = `https://${data.company_slug}.${cloudDomain}/`;
			} else {
				goto('/');
			}
		} catch (e: any) {
			error = e?.message ?? i18n.t('setup_error_default');
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{i18n.t('setup_title')} • fab.engineering</title>
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
		<!-- Logo -->
		<div class="flex items-center justify-center gap-2.5 mb-8">
			<div class="w-12 h-12 bg-primary rounded-xl flex items-center justify-center">
				<Layers class="w-6 h-6 text-primary-foreground" />
			</div>
			<div class="flex items-baseline">
				<span class="font-bold text-2xl tracking-tighter">fab</span>
				<span class="font-semibold text-2xl tracking-tighter text-muted-foreground">.engineering</span>
			</div>
		</div>

		<!-- Card -->
		<div class="rounded-2xl border bg-card p-8 shadow-sm">
			<h1 class="font-display text-xl tracking-tight text-center mb-1">{i18n.t('setup_title')}</h1>
			<p class="text-sm text-muted-foreground text-center mb-6">{i18n.t('setup_subtitle')}</p>

			<form onsubmit={submit} class="space-y-4">
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="name">{i18n.t('setup_name')}</label>
					<div class="relative">
						<User class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="name"
							type="text"
							bind:value={name}
							placeholder={i18n.t('setup_name_ph')}
							class="pl-9"
							autocomplete="name"
							required
						/>
					</div>
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="company">{i18n.t('setup_company')}</label>
					<div class="relative">
						<Building2 class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="company"
							type="text"
							bind:value={companyName}
							placeholder={i18n.t('setup_company_ph')}
							class="pl-9"
							required
						/>
					</div>
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="email">{i18n.t('setup_email')}</label>
					<div class="relative">
						<Mail class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="email"
							type="email"
							bind:value={email}
							placeholder={i18n.t('setup_email_ph')}
							class="pl-9"
							autocomplete="email"
							required
						/>
					</div>
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="password">{i18n.t('setup_password')}</label>
					<div class="relative">
						<Lock class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="password"
							type="password"
							bind:value={password}
							placeholder={i18n.t('setup_password_ph')}
							class="pl-9"
							autocomplete="new-password"
							required
						/>
					</div>
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="confirm">{i18n.t('setup_password_confirm')}</label>
					<div class="relative">
						<Lock class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="confirm"
							type="password"
							bind:value={confirmPassword}
							placeholder="••••••••"
							class="pl-9"
							autocomplete="new-password"
							required
						/>
					</div>
				</div>

				{#if error}
					<div class="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2.5 text-sm text-destructive">
						{error}
					</div>
				{/if}

				<Button
					type="submit"
					class="w-full"
					disabled={loading || !name || !email || !password || !confirmPassword || !companyName}
				>
					{#if loading}
						<Loader class="w-4 h-4 animate-spin" />
						{i18n.t('setup_submitting')}
					{:else}
						{i18n.t('setup_submit')}
					{/if}
				</Button>
			</form>
		</div>

		<p class="text-center text-xs text-muted-foreground mt-4">
			{i18n.t('setup_note')}
		</p>
	</div>
</div>
