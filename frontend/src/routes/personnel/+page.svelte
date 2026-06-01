<script lang="ts">
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Dialog from '$lib/components/ui/dialog.svelte';
	import Table from '$lib/components/ui/table.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import { Plus, Pencil, Trash2, Users } from '@lucide/svelte';

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

	// --- Form Dialog ---
	let showFormDialog = $state(false);
	let editingPerson: Person | null = $state(null);
	let formData = $state({ name: '', slug: '', role: '', model: 'claude-sonnet-4' });

	// Auto-generate slug from name when creating (not editing)
	$effect(() => {
		if (editingPerson === null) {
			formData.slug = slugify(formData.name);
		}
	});

	function slugify(text: string): string {
		return text
			.toLowerCase()
			.replace(/ğ/g, 'g').replace(/ş/g, 's').replace(/ı/g, 'i')
			.replace(/ö/g, 'o').replace(/ü/g, 'u').replace(/ç/g, 'c')
			.replace(/[^a-z0-9\s-]/g, '')
			.trim()
			.replace(/\s+/g, '-')
			.replace(/-+/g, '-');
	}

	function openCreate() {
		editingPerson = null;
		formData = { name: '', slug: '', role: '', model: 'claude-sonnet-4' };
		showFormDialog = true;
	}

	function openEdit(person: Person) {
		editingPerson = person;
		formData = {
			name: person.name,
			slug: person.slug,
			role: person.role,
			model: person.model ?? 'claude-sonnet-4'
		};
		showFormDialog = true;
	}

	function savePerson() {
		if (!formData.name || !formData.role) return;

		if (editingPerson) {
			personnel = personnel.map((p) =>
				p.id === editingPerson!.id
					? { ...p, ...formData }
					: p
			);
		} else {
			personnel = [
				...personnel,
				{
					id: Math.max(0, ...personnel.map((p) => p.id)) + 1,
					...formData,
					status: 'Active'
				}
			];
		}

		showFormDialog = false;
	}

	// --- Delete Dialog ---
	let deleteTarget: Person | null = $state(null);
	let showDeleteDialog = $state(false);

	function requestDelete(person: Person) {
		deleteTarget = person;
		showDeleteDialog = true;
	}

	function confirmDelete() {
		if (!deleteTarget) return;
		personnel = personnel.filter((p) => p.id !== deleteTarget!.id);
		deleteTarget = null;
		showDeleteDialog = false;
	}

	function cancelDelete() {
		deleteTarget = null;
		showDeleteDialog = false;
	}

	const MODEL_OPTIONS = [
		{ value: 'claude-sonnet-4', label: 'Claude Sonnet 4' },
		{ value: 'claude-opus-4', label: 'Claude Opus 4' },
		{ value: 'gpt-4o', label: 'GPT-4o' },
		{ value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
		{ value: 'grok-4.3', label: 'Grok 4.3' }
	];
</script>

<svelte:head>
	<title>Personel • 3rdParty Agent</title>
</svelte:head>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">Personel</h1>
			<p class="text-muted-foreground mt-1">Tüm personeli görüntüle ve yönet</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="h-4 w-4" />
			Yeni Personel
		</Button>
	</div>

	<!-- Table or Empty State -->
	{#if personnel.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
				<Users class="w-6 h-6 text-muted-foreground" />
			</div>
			<div>
				<p class="font-medium">Henüz personel yok</p>
				<p class="text-sm text-muted-foreground mt-1">İlk personeli eklemek için butona tıklayın.</p>
			</div>
			<Button onclick={openCreate} size="sm" class="mt-2">
				<Plus class="h-4 w-4" />
				Yeni Personel
			</Button>
		</div>
	{:else}
		<div class="rounded-xl border bg-card overflow-hidden">
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
					{#each personnel as person (person.id)}
						<tr class="hover:bg-muted/30 transition-colors">
							<td class="px-4 py-3">
								<div class="flex items-center gap-3">
									<img
										src="https://i.pravatar.cc/36?img={person.id}"
										class="h-9 w-9 rounded-lg ring-1 ring-border flex-shrink-0"
										alt=""
										aria-hidden="true"
									/>
									<div>
										<div class="font-medium">{person.name}</div>
										<div class="text-xs text-muted-foreground font-mono md:hidden">/{person.slug}</div>
									</div>
								</div>
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden md:table-cell">
								{person.role}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell font-mono text-xs">
								{person.model ?? '-'}
							</td>
							<td class="px-4 py-3">
								<Badge variant={person.status === 'Active' ? 'default' : 'secondary'}>
									{person.status === 'Active' ? 'Aktif' : 'Taslak'}
								</Badge>
							</td>
							<td class="px-4 py-3">
								<div class="flex justify-end gap-1">
									<Button
										variant="ghost"
										size="icon"
										onclick={() => openEdit(person)}
										aria-label="Düzenle"
									>
										<Pencil class="h-4 w-4" />
									</Button>
									<Button
										variant="ghost"
										size="icon"
										onclick={() => requestDelete(person)}
										aria-label="Sil"
										class="text-destructive hover:text-destructive hover:bg-destructive/10"
									>
										<Trash2 class="h-4 w-4" />
									</Button>
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</Table>
		</div>
	{/if}
</div>

<!-- Create / Edit Dialog -->
<Dialog bind:open={showFormDialog} label={editingPerson ? 'Personeli Düzenle' : 'Yeni Personel Ekle'}>
	<div class="space-y-5">
		<div>
			<h2 class="font-display text-xl tracking-tight">
				{editingPerson ? 'Personeli Düzenle' : 'Yeni Personel Ekle'}
			</h2>
		</div>

		<div class="space-y-4">
			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="person-name">Ad Soyad</label>
				<Input
					id="person-name"
					bind:value={formData.name}
					placeholder="Ahmet Yılmaz"
					autocomplete="off"
				/>
			</div>

			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="person-slug">Slug</label>
				<Input
					id="person-slug"
					bind:value={formData.slug}
					placeholder="ahmet-yilmaz"
					autocomplete="off"
					class="font-mono text-xs"
				/>
			</div>

			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="person-role">Rol / Ünvan</label>
				<Input
					id="person-role"
					bind:value={formData.role}
					placeholder="Yazılım Mühendisi"
					autocomplete="off"
				/>
			</div>

			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="person-model">Model</label>
				<select
					id="person-model"
					class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
					bind:value={formData.model}
				>
					{#each MODEL_OPTIONS as opt}
						<option value={opt.value}>{opt.label}</option>
					{/each}
				</select>
			</div>
		</div>

		<div class="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
			<Button variant="outline" onclick={() => (showFormDialog = false)} class="sm:w-auto">
				İptal
			</Button>
			<Button onclick={savePerson} disabled={!formData.name || !formData.role} class="sm:w-auto">
				{editingPerson ? 'Güncelle' : 'Ekle'}
			</Button>
		</div>
	</div>
</Dialog>

<!-- Delete Confirmation Dialog -->
<Dialog bind:open={showDeleteDialog} label="Silme Onayı">
	<div class="space-y-4">
		<div>
			<h2 class="font-display text-xl tracking-tight">Personeli Sil</h2>
			<p class="text-sm text-muted-foreground mt-1">
				<strong class="text-foreground">{deleteTarget?.name}</strong> adlı personeli kalıcı olarak
				silmek istediğinize emin misiniz? Bu işlem geri alınamaz.
			</p>
		</div>

		<div class="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
			<Button variant="outline" onclick={cancelDelete} class="sm:w-auto">İptal</Button>
			<Button variant="destructive" onclick={confirmDelete} class="sm:w-auto">Sil</Button>
		</div>
	</div>
</Dialog>
