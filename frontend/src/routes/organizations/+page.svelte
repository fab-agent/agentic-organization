<script lang="ts">
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Dialog from '$lib/components/ui/dialog.svelte';
	import Table from '$lib/components/ui/table.svelte';
	import { Plus, Pencil, Trash2 } from '@lucide/svelte';

	type Organization = {
		id: number;
		name: string;
		slug: string;
		description: string;
		status: 'Active' | 'Inactive';
	};

	let organizations: Organization[] = $state([
		{ id: 1, name: 'Acme Corp', slug: 'acme-corp', description: 'Teknoloji odaklı inovatif şirket', status: 'Active' },
		{ id: 2, name: 'TechNova', slug: 'technova', description: 'Yazılım ve AI çözümleri', status: 'Active' }
	]);

	let showDialog = $state(false);
	let editingOrg: Organization | null = $state(null);
	let formData = $state({ name: '', slug: '', description: '' });

	function openCreate() {
		editingOrg = null;
		formData = { name: '', slug: '', description: '' };
		showDialog = true;
	}

	function openEdit(org: Organization) {
		editingOrg = org;
		formData = { name: org.name, slug: org.slug, description: org.description };
		showDialog = true;
	}

	function saveOrganization() {
		if (!formData.name || !formData.slug) return;

		if (editingOrg) {
			// Update
			organizations = organizations.map((org) =>
				org.id === editingOrg!.id
					? { ...org, ...formData, status: org.status }
					: org
			);
		} else {
			// Create
			const newOrg: Organization = {
				id: Math.max(0, ...organizations.map((o) => o.id)) + 1,
				...formData,
				status: 'Active'
			};
			organizations = [...organizations, newOrg];
		}

		showDialog = false;
	}

	function deleteOrganization(id: number) {
		if (confirm('Bu organizasyonu silmek istediğinize emin misiniz?')) {
			organizations = organizations.filter((org) => org.id !== id);
		}
	}
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl font-semibold tracking-tight">Organizasyonlar</h1>
			<p class="text-muted-foreground mt-1">Tüm organizasyonları görüntüle ve yönet</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="mr-2 h-4 w-4" />
			Yeni Organizasyon
		</Button>
	</div>

	<!-- Table -->
	<div class="rounded-xl border bg-card">
		<Table>
			<thead>
				<tr class="border-b bg-muted/50 text-left text-sm font-medium text-muted-foreground">
					<th class="h-12 px-4">Organizasyon</th>
					<th class="h-12 px-4 hidden md:table-cell">Slug</th>
					<th class="h-12 px-4 hidden lg:table-cell">Açıklama</th>
					<th class="h-12 px-4">Durum</th>
					<th class="h-12 w-[100px] px-4 text-right">İşlemler</th>
				</tr>
			</thead>
			<tbody class="divide-y">
				{#each organizations as org}
					<tr class="hover:bg-muted/30 transition-colors">
						<td class="px-4 py-3 font-medium">{org.name}</td>
						<td class="px-4 py-3 text-sm text-muted-foreground hidden md:table-cell">/{org.slug}</td>
						<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell max-w-[300px] truncate">
							{org.description}
						</td>
						<td class="px-4 py-3">
							<Badge variant={org.status === 'Active' ? 'default' : 'secondary'}>
								{org.status}
							</Badge>
						</td>
						<td class="px-4 py-3">
							<div class="flex justify-end gap-2">
								<Button variant="ghost" size="sm" onclick={() => openEdit(org)}>
									<Pencil class="h-4 w-4" />
								</Button>
								<Button variant="ghost" size="sm" onclick={() => deleteOrganization(org.id)}>
									<Trash2 class="h-4 w-4 text-destructive" />
								</Button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</Table>
	</div>

	<!-- Empty state -->
	{#if organizations.length === 0}
		<div class="text-center py-12 text-muted-foreground">Henüz organizasyon yok.</div>
	{/if}
</div>

<!-- Create/Edit Dialog -->
<Dialog bind:open={showDialog}>
	<div class="space-y-4">
		<div>
			<h2 class="font-display text-xl font-semibold tracking-tight">
				{editingOrg ? 'Organizasyonu Düzenle' : 'Yeni Organizasyon'}
			</h2>
			<p class="text-sm text-muted-foreground mt-1">
				{editingOrg ? 'Mevcut organizasyon bilgilerini güncelleyin.' : 'Yeni bir organizasyon oluşturun.'}
			</p>
		</div>

		<div class="space-y-4 pt-2">
			<div>
				<label class="text-sm font-medium mb-1.5 block">Organizasyon Adı</label>
				<input
					type="text"
					class="flex h-9 w-full rounded-md border bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
					bind:value={formData.name}
					placeholder="Acme Corp"
				/>
			</div>
			<div>
				<label class="text-sm font-medium mb-1.5 block">Slug</label>
				<input
					type="text"
					class="flex h-9 w-full rounded-md border bg-background px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
					bind:value={formData.slug}
					placeholder="acme-corp"
				/>
			</div>
			<div>
				<label class="text-sm font-medium mb-1.5 block">Açıklama</label>
				<textarea
					class="flex min-h-[80px] w-full rounded-md border bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 resize-y"
					bind:value={formData.description}
					placeholder="Kısa açıklama..."
				></textarea>
			</div>
		</div>

		<div class="flex flex-col-reverse gap-3 pt-4 sm:flex-row sm:justify-end">
			<Button variant="outline" onclick={() => (showDialog = false)} class="w-full sm:w-auto">
				İptal
			</Button>
			<Button onclick={saveOrganization} class="w-full sm:w-auto">
				{editingOrg ? 'Güncelle' : 'Oluştur'}
			</Button>
		</div>
	</div>
</Dialog>
