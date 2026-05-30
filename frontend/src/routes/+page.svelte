<script>
	import { Button } from '$lib/components/ui/button';
	import { Card } from '$lib/components/ui/card';
	import { Plus, Building2, Edit } from 'lucide-svelte';

	let title = 'Dashboard';
</script>

<svelte:head>
	<title>{title} • 3rdParty Agent</title>
</svelte:head>

<div class="space-y-8">
	<!-- Header -->
	<div class="flex items-end justify-between">
		<div>
			<h1 class="font-semibold text-3xl tracking-tighter">Dashboard</h1>
			<p class="text-muted-foreground mt-1.5">Acme Corp • Genel bakış</p>
		</div>

		<Button class="gap-x-2">
			<Plus class="w-4 h-4" />
			<span>Yeni Personel</span>
		</Button>
	</div>

	<!-- Stats Cards -->
	<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
		<Card class="p-6">
			<div class="text-sm text-muted-foreground">Toplam Personel</div>
			<div class="text-4xl font-semibold tracking-tighter mt-2">12</div>
		</Card>

		<Card class="p-6">
			<div class="text-sm text-muted-foreground">Aktif Ajan</div>
			<div class="text-4xl font-semibold tracking-tighter mt-2 text-emerald-600">8</div>
		</Card>

		<Card class="p-6">
			<div class="text-sm text-muted-foreground">Departman</div>
			<div class="text-4xl font-semibold tracking-tighter mt-2">4</div>
		</Card>

		<Card class="p-6">
			<div class="text-sm text-muted-foreground">Policy Dosyası</div>
			<div class="text-4xl font-semibold tracking-tighter mt-2">9</div>
		</Card>
	</div>

	<!-- Company.md Card -->
	<Card class="p-6">
		<div class="flex items-center justify-between mb-5">
			<div class="flex items-center gap-x-3">
				<div class="w-9 h-9 rounded-xl bg-muted flex items-center justify-center">
					<Building2 class="w-4.5 h-4.5 text-muted-foreground" />
				</div>
				<div>
					<div class="font-semibold tracking-tight">company.md</div>
					<div class="text-xs text-muted-foreground">Vizyon • Misyon • Değerler • Hedefler</div>
				</div>
			</div>

			<Button variant="outline" size="sm" class="gap-x-2 text-xs h-8">
				<Edit class="w-3.5 h-3.5" />
				<span>Düzenle</span>
			</Button>
		</div>

		<div class="prose prose-sm max-w-none text-muted-foreground">
			<div class="font-medium text-foreground mb-2">Acme Corp</div>
			<div><strong>Vizyon:</strong> Teknoloji ile iş süreçlerini dönüştüren lider organizasyon olmak.</div>

			<div class="mt-5 font-medium text-foreground">Current Goals (Q2 2026):</div>
			<ul class="text-sm mt-2 space-y-2 list-none pl-0">
				<li class="flex items-center gap-x-2.5">
					<input type="checkbox" checked class="accent-primary" />
					Agentic süreçleri 3 departmanda devreye almak
				</li>
				<li class="flex items-center gap-x-2.5">
					<input type="checkbox" checked class="accent-primary" />
					15 aktif ajan oluşturmak
				</li>
			</ul>
		</div>
	</Card>
</div>
