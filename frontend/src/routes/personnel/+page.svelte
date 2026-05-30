<script lang="ts">
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Dialog from '$lib/components/ui/dialog.svelte';
	import Table from '$lib/components/ui/table.svelte';
	import { Plus, Pencil, Trash2 } from '@lucide/svelte';

	type Person = {
		id: number;
		name: string;
		slug: string;
		role: string;
		status: 'Active' | 'Draft';
		model?: string;
	};

	let personnel: Person[] = $state([
		{ id: 1, name: 'John Doe', slug: 'john-doe', role: 'Senior Software Engineer', status: 'Active', model: 'claude-sonnet-4' },
		{ id: 2, name: 'Sarah Chen', slug: 'sarah-chen', role: 'Head of Marketing', status: 'Active', model: 'gpt-4o' },
		{ id: 3, name: 'Mehmet Yılmaz', slug: 'mehmet-yilmaz', role: 'AI Researcher', status: 'Draft', model: 'claude-sonnet-4' }
	]);

	let showDialog = $state(false);
	let editingPerson: Person | null = $state(null);
	let formData = $state({ name: '', slug: '', role: '', model: 'claude-sonnet-4' });

	function openCreate() {
		editingPerson = null;
		formData = { name: '', slug: '', role: '', model: 'claude-sonnet-4' };
		showDialog = true;
	}

	function openEdit(person: Person) {
		editingPerson = person;
		formData = {
			name: person.name,
			slug: person.slug,
			role: person.role,
			model: person.model || 'claude-sonnet-4'
		};
		showDialog = true;
	}

	function savePerson() {
		if (!formData.name || !formData.role) return;

		if (editingPerson) {
			personnel = personnel.map((p) =>
				p.id === editingPerson!.id
					? { ...p, ...formData, status: p.status }
					: p
			);
		} else {
			const newPerson: Person = {
				id: Math.max(0, ...personnel.map((p) => p.id)) + 1,
				...formData,
				status: 'Active'
			};
			personnel = [...personnel, newPerson];
		}

		showDialog = false;
	}

	function deletePerson(id: number) {
		if (confirm('Bu personeli silmek istediğinize emin misiniz?')) {
			personnel = personnel.filter((p) => p.id !== id);
		}
	}
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl font-semibold tracking-tight">Personel</h1>
			<p class="text-muted-foreground mt-1">Tüm personeli görüntüle ve yönet</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="mr-2 h-4 w-4" />
			Yeni Personel
		</Button>
	</div>

	<!-- Table -->
	<div class="rounded-xl border bg-card">
		<Table>
			<thead>
				<tr class="border-b bg-muted/50 text-left text-sm font-medium text-muted-foreground">
					<th class="h-12 px-4">Personel</th>
					<th class="h-12 px-4 hidden md:table-cell">Rol / Ünvan</th>
					<th class="h-12 px-4 hidden lg:table-cell">Model</th>
					<th class="h-12 px-4">Durum</th>
					<th class="h-12 w-[100px] px-4 text-right">İşlemler</th>
				</tr>
			</thead>
			<tbody class="divide-y">
				{#each personnel as person}
					<tr class="hover:bg-muted/30 transition-colors">
						<td class="px-4 py-3">
							<div class="flex items-center gap-3">
								<img
									src="https://i.pravatar.cc/36?img={person.id}"
									class="h-9 w-9 rounded-lg ring-1 ring-border"
									alt={person.name}
								/>
								<div>
									<div class="font-medium">{person.name}</div>
									<div class="text-xs text-muted-foreground md:hidden">/{person.slug}</div>
								</div>
							</div>
						</td>
						<td class="px-4 py-3 text-sm text-muted-foreground hidden md:table-cell">{person.role}</td>
						<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell">
							{person.model || '-'}
						</td>
						<td class="px-4 py-3">
							<Badge variant={person.status === 'Active' ? 'default' : 'secondary'}>
								{person.status}
							</Badge>
						</td>
						<td class="px-4 py-3">
							<div class="flex justify-end gap-2">
								<Button variant="ghost" size="sm" onclick={() => openEdit(person)}>
									<Pencil class="h-4 w-4" />
								</Button>
								<Button variant="ghost" size="sm" onclick={() => deletePerson(person.id)}>
									<Trash2 class="h-4 w-4 text-destructive" />
								</Button>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</Table>
	</div>

	{#if personnel.length === 0}
		<div class="text-center py-12 text-muted-foreground">Henüz personel yok.</div>
	{/if}
</div>

<!-- Create/Edit Dialog -->
<Dialog bind:open={showDialog}>
	<div class="space-y-4">
		<div>
			<h2 class="font-display text-xl font-semibold tracking-tight">
				{editingPerson ? 'Personeli Düzenle' : 'Yeni Personel Ekle'}
			</h2>
		</div>

		<div class="space-y-4 pt-2">
			<div>
				<label class="text-sm font-medium mb-1.5 block">Ad Soyad</label>
				<input
					type="text"
					class="flex h-9 w-full rounded-md border bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
					bind:value={formData.name}
					placeholder="Ahmet Yılmaz"
				/>
			</div>
			<div>
				<label class="text-sm font-medium mb-1.5 block">Rol / Ünvan</label>
				<input
					type="text"
					class="flex h-9 w-full rounded-md border bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
					bind:value={formData.role}
					placeholder="Yazılım Mühendisi"
				/>
			</div>
			<div>
				<label class="text-sm font-medium mb-1.5 block">Model</label>
				<select
					class="flex h-9 w-full rounded-md border bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
					bind:value={formData.model}
				>
					<option value="claude-sonnet-4">claude-sonnet-4</option>
					<option value="gpt-4o">gpt-4o</option>
					<option value="gemini-2.5-pro">gemini-2.5-pro</option>
				</select>
			</div>
		</div>

		<div class="flex flex-col-reverse gap-3 pt-4 sm:flex-row sm:justify-end">
			<Button variant="outline" onclick={() => (showDialog = false)} class="w-full sm:w-auto">
				İptal
			</Button>
			<Button onclick={savePerson} class="w-full sm:w-auto">
				{editingPerson ? 'Güncelle' : 'Ekle'}
			</Button>
		</div>
	</div>
</Dialog>
