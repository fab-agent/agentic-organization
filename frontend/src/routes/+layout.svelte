<script>
	import '../app.css';
	import { page } from '$app/stores';
	import { Button } from '$lib/components/ui/button';
	import {
		LayoutDashboard,
		Building2,
		Users,
		Bot,
		User,
		ChevronDown
	} from 'lucide-svelte';
</script>

<div class="min-h-screen bg-background">
	<!-- Top Navigation (Shadcn style) -->
	<div class="border-b bg-card">
		<div class="max-w-screen-2xl mx-auto">
			<div class="flex items-center justify-between px-6 h-14">
				<!-- Logo -->
				<div class="flex items-center gap-x-3">
					<div class="flex items-center gap-x-2.5">
						<div class="w-8 h-8 bg-primary rounded-xl flex items-center justify-center">
							<Bot class="w-4.5 h-4.5 text-primary-foreground" />
						</div>
						<div class="flex items-baseline">
							<span class="font-semibold text-xl tracking-tighter">3rdParty</span>
							<span class="font-semibold text-xl tracking-tighter text-muted-foreground">Agent</span>
						</div>
					</div>
				</div>

				<!-- Right side: Org + User -->
				<div class="flex items-center gap-x-3">
					<div class="flex items-center gap-x-2 px-3 py-1.5 rounded-full bg-muted/50 text-sm">
						<div class="w-2 h-2 bg-emerald-500 rounded-full"></div>
						<span class="text-muted-foreground font-medium">Acme Corp</span>
					</div>

					<Button variant="ghost" size="sm" class="gap-x-2 px-2">
						<div class="flex items-center gap-x-2">
							<div class="w-7 h-7 rounded-full bg-muted flex items-center justify-center ring-1 ring-border">
								<User class="w-4 h-4 text-muted-foreground" />
							</div>
							<span class="text-sm font-medium">Kuntay Kunt</span>
							<ChevronDown class="w-4 h-4 text-muted-foreground" />
						</div>
					</Button>
				</div>
			</div>
		</div>
	</div>

	<div class="max-w-screen-2xl mx-auto flex">
		<!-- Sidebar (Shadcn style) -->
		<div class="w-60 border-r bg-card min-h-[calc(100vh-3.5rem)] p-3">
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

				<a href="/organizations">
					<Button
						variant={$page.url.pathname.startsWith('/organizations') ? 'secondary' : 'ghost'}
						class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium"
					>
						<Building2 class="w-4 h-4" />
						<span>Organizasyon</span>
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

				<a href="#">
					<Button
						variant="ghost"
						class="w-full justify-start gap-x-3 h-10 rounded-xl text-sm font-medium text-muted-foreground"
					>
						<Bot class="w-4 h-4" />
						<span>Ajanlar</span>
					</Button>
				</a>
			</div>

			<!-- Organization info -->
			<div class="mt-8 px-3">
				<div class="text-[10px] font-semibold text-muted-foreground tracking-[1.5px] mb-2 px-2">ORGANİZASYON</div>
				<div class="px-3 py-3 bg-muted/60 rounded-2xl text-sm border border-border/50">
					<div class="font-semibold">Acme Corp</div>
					<div class="text-xs text-muted-foreground mt-0.5">12 personel • 8 ajan</div>
				</div>
			</div>
		</div>

		<!-- Main Content -->
		<div class="flex-1 p-8">
			<slot />
		</div>
	</div>
</div>
