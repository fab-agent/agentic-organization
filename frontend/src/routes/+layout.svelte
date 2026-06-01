<script lang="ts">
	import '../app.css';
	import { page } from '$app/stores';
	import Button from '$lib/components/ui/button.svelte';
	import {
		LayoutDashboard,
		Layers,
		Users,
		Bot,
		ChevronDown,
		Menu,
		X,
		Network
	} from '@lucide/svelte';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	let sidebarOpen = $state(false);

	// Close sidebar on route change
	$effect(() => {
		$page.url.pathname;
		sidebarOpen = false;
	});
</script>

<div class="min-h-screen bg-background">
	<!-- Top Navigation -->
	<div class="border-b bg-card">
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
						<div class="w-8 h-8 bg-primary rounded-xl flex items-center justify-center">
							<Bot class="w-4 h-4 text-primary-foreground" />
						</div>
						<div class="flex items-baseline">
							<span class="font-semibold text-xl tracking-tighter">3rdParty</span>
							<span class="font-semibold text-xl tracking-tighter text-muted-foreground">Agent</span>
						</div>
					</div>
				</div>

				<!-- Right: Org badge + User -->
				<div class="flex items-center gap-x-3">
					<div class="hidden sm:flex items-center gap-x-2 px-3 py-1.5 rounded-full bg-muted/50 text-sm">
						<div class="w-2 h-2 bg-emerald-500 rounded-full"></div>
						<span class="text-muted-foreground font-medium">Acme Corp</span>
					</div>

					<a href="/profile">
						<Button variant="ghost" size="sm" class="gap-x-2 px-2">
							<div class="flex items-center gap-x-2">
								<div class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center ring-1 ring-border text-xs font-bold text-primary">
									KK
								</div>
								<span class="hidden sm:block text-sm font-medium">Kuntay Kunt</span>
								<ChevronDown class="w-4 h-4 text-muted-foreground" />
							</div>
						</Button>
					</a>
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
					<div class="w-7 h-7 bg-primary rounded-lg flex items-center justify-center">
						<Bot class="w-3.5 h-3.5 text-primary-foreground" />
					</div>
					<span class="font-semibold tracking-tight">3rdParty Agent</span>
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
				<div class="space-y-1 px-1 pt-2">
					<a href="/">
						<Button
							variant={$page.url.pathname === '/' ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium"
						>
							<LayoutDashboard class="w-4 h-4" />
							<span>Dashboard</span>
						</Button>
					</a>

					<a href="/departments">
						<Button
							variant={$page.url.pathname.startsWith('/departments') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium"
						>
							<Layers class="w-4 h-4" />
							<span>Departmanlar</span>
						</Button>
					</a>

					<a href="/personnel">
						<Button
							variant={$page.url.pathname.startsWith('/personnel') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium"
						>
							<Users class="w-4 h-4" />
							<span>Personel</span>
						</Button>
					</a>

					<a href="/org-chart">
						<Button
							variant={$page.url.pathname.startsWith('/org-chart') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium"
						>
							<Network class="w-4 h-4" />
							<span>Org Şeması</span>
						</Button>
					</a>

					<a href="/agents">
						<Button
							variant={$page.url.pathname.startsWith('/agents') ? 'secondary' : 'ghost'}
							class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium"
						>
							<Bot class="w-4 h-4" />
							<span>Ajanlar</span>
						</Button>
					</a>
				</div>

				<!-- Company info -->
				<div class="mt-8 px-1">
					<div class="text-[10px] font-semibold text-muted-foreground tracking-[1.5px] mb-2 px-2">
						ŞİRKET
					</div>
					<div class="px-3 py-3 bg-muted/60 rounded-2xl text-sm border border-border/50">
						<div class="font-semibold">Acme Corp</div>
						<div class="text-xs text-muted-foreground mt-0.5">4 departman • 10 personel • 6 ajan</div>
					</div>
				</div>
			</div>
		</aside>

		<!-- Main Content -->
		<div class="flex-1 min-w-0 p-8">
			{@render children()}
		</div>
	</div>
</div>
