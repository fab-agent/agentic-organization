<script lang="ts">
	import { goto } from '$app/navigation';
	import { Layers, User, Mail, Lock, Building2, Loader } from '@lucide/svelte';
	import Button from '$lib/components/ui/button.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import { authStore } from '$lib/stores/auth.svelte';

	const API = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';

	let name = $state('');
	let email = $state('');
	let password = $state('');
	let confirmPassword = $state('');
	let companyName = $state('');
	let error = $state('');
	let loading = $state(false);

	async function submit(e: Event) {
		e.preventDefault();
		error = '';

		if (password !== confirmPassword) {
			error = 'Şifreler eşleşmiyor';
			return;
		}
		if (password.length < 8) {
			error = 'Şifre en az 8 karakter olmalı';
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
			if (!res.ok) throw new Error(data.detail ?? 'Kurulum başarısız');

			// Store token and login with the new credentials
			await authStore.login(email, password);
			goto('/');
		} catch (e: any) {
			error = e?.message ?? 'Kurulum başarısız';
		} finally {
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Kurulum • fab.engineering</title>
</svelte:head>

<div class="min-h-screen bg-background flex items-center justify-center p-4">
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
			<h1 class="font-display text-xl tracking-tight text-center mb-1">Sistemi Kur</h1>
			<p class="text-sm text-muted-foreground text-center mb-6">
				İlk yönetici hesabını oluşturarak başla
			</p>

			<form onsubmit={submit} class="space-y-4">
				<!-- Ad Soyad -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="name">Ad Soyad</label>
					<div class="relative">
						<User class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="name"
							type="text"
							bind:value={name}
							placeholder="Kuntay Kunt"
							class="pl-9"
							autocomplete="name"
							required
						/>
					</div>
				</div>

				<!-- Şirket Adı -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="company">Şirket Adı</label>
					<div class="relative">
						<Building2 class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="company"
							type="text"
							bind:value={companyName}
							placeholder="Fabrika Yazılım"
							class="pl-9"
							required
						/>
					</div>
				</div>

				<!-- E-posta -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="email">E-posta</label>
					<div class="relative">
						<Mail class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="email"
							type="email"
							bind:value={email}
							placeholder="ad@sirket.com"
							class="pl-9"
							autocomplete="email"
							required
						/>
					</div>
				</div>

				<!-- Şifre -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="password">Şifre</label>
					<div class="relative">
						<Lock class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
						<Input
							id="password"
							type="password"
							bind:value={password}
							placeholder="En az 8 karakter"
							class="pl-9"
							autocomplete="new-password"
							required
						/>
					</div>
				</div>

				<!-- Şifre Tekrar -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="confirm">Şifre Tekrar</label>
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
						Kuruluyor...
					{:else}
						Kurulumu Tamamla
					{/if}
				</Button>
			</form>
		</div>

		<p class="text-center text-xs text-muted-foreground mt-4">
			Bu form yalnızca ilk kurulumda görünür.
		</p>
	</div>
</div>
