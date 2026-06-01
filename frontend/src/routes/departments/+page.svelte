<script lang="ts">
	import { onMount } from 'svelte';
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import {
		Plus,
		Pencil,
		Trash2,
		Layers,
		X,
		Target,
		ShieldCheck,
		AlertCircle,
		Loader
	} from '@lucide/svelte';
	import { departments as deptApi, type Department } from '$lib/api/departments';

	// ── State ─────────────────────────────────────────────────────────────────
	let departments: Department[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);

	async function loadDepartments() {
		try {
			loading = true;
			error = null;
			departments = await deptApi.list();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	onMount(loadDepartments);

	// ── Derived stats ──────────────────────────────────────────────────────────
	const activeDepts = $derived(departments.filter((d) => d.status === 'Active').length);

	// ── Panel state ───────────────────────────────────────────────────────────
	let panelOpen    = $state(false);
	let saving       = $state(false);
	let editingDept: Department | null = $state(null);

	type FormData = {
		name: string;
		slug: string;
		description: string;
		goals: string;
		policies: string[];
		status: 'Active' | 'Inactive';
	};

	let form: FormData = $state({
		name: '',
		slug: '',
		description: '',
		goals: '',
		policies: [],
		status: 'Active'
	});

	let newPolicyInput = $state('');

	// Slug auto-gen
	$effect(() => {
		if (!editingDept) {
			form.slug = slugify(form.name);
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
		editingDept = null;
		form = { name: '', slug: '', description: '', goals: '', policies: [], status: 'Active' };
		newPolicyInput = '';
		panelOpen = true;
	}

	function openEdit(dept: Department) {
		editingDept = dept;
		form = {
			name: dept.name,
			slug: dept.slug,
			description: dept.description ?? '',
			goals: dept.goals ?? '',
			policies: [...dept.policies],
			status: dept.status
		};
		newPolicyInput = '';
		panelOpen = true;
	}

	function closePanel() {
		panelOpen = false;
		editingDept = null;
	}

	async function saveDepartment() {
		if (!form.name || !form.slug) return;
		saving = true;
		try {
			if (editingDept) {
				const updated = await deptApi.update(editingDept.id, {
					name: form.name, slug: form.slug,
					description: form.description || null,
					goals: form.goals || null,
					policies: form.policies,
					status: form.status,
				});
				departments = departments.map((d) => d.id === updated.id ? updated : d);
			} else {
				const created = await deptApi.create({
					name: form.name, slug: form.slug,
					description: form.description || null,
					goals: form.goals || null,
					policies: form.policies,
					status: form.status,
				});
				departments = [...departments, created];
			}
			closePanel();
		} catch (e) {
			alert((e as Error).message);
		} finally {
			saving = false;
		}
	}

	function addPolicy() {
		const trimmed = newPolicyInput.trim();
		if (!trimmed || form.policies.includes(trimmed)) return;
		form.policies = [...form.policies, trimmed];
		newPolicyInput = '';
	}

	function removePolicy(policy: string) {
		form.policies = form.policies.filter((p) => p !== policy);
	}

	// ── Delete ─────────────────────────────────────────────────────────────────
	let deleteTarget: Department | null = $state(null);
	let showDeleteDialog = $state(false);

	function requestDelete(dept: Department) {
		deleteTarget = dept;
		showDeleteDialog = true;
	}

	async function confirmDelete() {
		if (!deleteTarget) return;
		try {
			await deptApi.delete(deleteTarget.id);
			departments = departments.filter((d) => d.id !== deleteTarget!.id);
		} catch (e) {
			alert((e as Error).message);
		} finally {
			deleteTarget = null;
			showDeleteDialog = false;
		}
	}

	// ── Helpers ────────────────────────────────────────────────────────────────
	function goalCount(goals: string | null): number {
		return (goals ?? '').split('\n').filter((l) => l.trim()).length;
	}
</script>

<svelte:head>
	<title>Departmanlar • 3rdParty Agent</title>
</svelte:head>

<div class={['space-y-6 transition-all duration-200', panelOpen ? 'lg:mr-[608px]' : ''].join(' ')}>

	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">Departmanlar</h1>
			<p class="text-muted-foreground mt-1">Şirket departmanlarını, hedefleri ve politikaları yönet</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="h-4 w-4" />
			Yeni Departman
		</Button>
	</div>

	<!-- Stats -->
	<div class="grid grid-cols-2 gap-4 sm:grid-cols-2">
		<div class="rounded-xl border bg-card p-4">
			<div class="text-2xl font-bold">{departments.length}</div>
			<div class="text-xs text-muted-foreground mt-0.5">Toplam Departman</div>
		</div>
		<div class="rounded-xl border bg-card p-4">
			<div class="text-2xl font-bold text-emerald-600">{activeDepts}</div>
			<div class="text-xs text-muted-foreground mt-0.5">Aktif</div>
		</div>
	</div>

	<!-- Error -->
	{#if error}
		<div class="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 flex items-center gap-2 text-sm text-destructive">
			<AlertCircle class="w-4 h-4 flex-shrink-0" />
			{error}
			<button onclick={loadDepartments} class="ml-auto underline text-xs">Tekrar dene</button>
		</div>
	{/if}

	<!-- Table or Empty State -->
	{#if loading}
		<div class="rounded-xl border bg-card flex items-center justify-center py-20 gap-2 text-muted-foreground">
			<Loader class="w-4 h-4 animate-spin" />
			<span class="text-sm">Yükleniyor...</span>
		</div>
	{:else if departments.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
				<Layers class="w-6 h-6 text-muted-foreground" />
			</div>
			<div>
				<p class="font-medium">Henüz departman yok</p>
				<p class="text-sm text-muted-foreground mt-1">İlk departmanı oluşturmak için butona tıklayın.</p>
			</div>
			<Button onclick={openCreate} size="sm" class="mt-2">
				<Plus class="h-4 w-4" />
				Yeni Departman
			</Button>
		</div>
	{:else}
		<div class="rounded-xl border bg-card overflow-hidden">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b bg-muted/50 text-left text-sm font-medium text-muted-foreground">
						<th class="h-12 px-4">Departman</th>
						<th class="h-12 px-4 hidden md:table-cell">Hedef</th>
						<th class="h-12 px-4 hidden lg:table-cell">Politika</th>

						<th class="h-12 px-4">Durum</th>
						<th class="h-12 w-[90px] px-4 text-right">İşlem</th>
					</tr>
				</thead>
				<tbody class="divide-y">
					{#each departments as dept (dept.id)}
						<tr class="hover:bg-muted/30 transition-colors group">
							<!-- Dept name + description -->
							<td class="px-4 py-3">
								<div class="flex items-center gap-2.5">
									<div class="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center flex-shrink-0">
										<Layers class="w-4 h-4 text-indigo-600" />
									</div>
									<div class="min-w-0">
										<div class="font-medium truncate">{dept.name}</div>
										<div class="text-xs text-muted-foreground font-mono">/{dept.slug}</div>
									</div>
								</div>
							</td>

							<!-- Goal count -->
							<td class="px-4 py-3 hidden md:table-cell">
								<div class="flex items-center gap-1.5 text-muted-foreground">
									<Target class="w-3.5 h-3.5 flex-shrink-0" />
									<span>{goalCount(dept.goals)} hedef</span>
								</div>
							</td>

							<!-- Policy count -->
							<td class="px-4 py-3 hidden lg:table-cell">
								<div class="flex items-center gap-1.5 text-muted-foreground">
									<ShieldCheck class="w-3.5 h-3.5 flex-shrink-0" />
									<span>{dept.policies.length} politika</span>
								</div>
							</td>

							<!-- Status -->
							<td class="px-4 py-3">
								<Badge variant={dept.status === 'Active' ? 'default' : 'secondary'}>
									{dept.status === 'Active' ? 'Aktif' : 'Pasif'}
								</Badge>
							</td>

							<!-- Actions -->
							<td class="px-4 py-3">
								<div class="flex justify-end gap-1">
									<Button
										variant="ghost"
										size="icon"
										onclick={() => openEdit(dept)}
										aria-label="Düzenle"
									>
										<Pencil class="h-4 w-4" />
									</Button>
									<Button
										variant="ghost"
										size="icon"
										onclick={() => requestDelete(dept)}
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
			</table>
		</div>
	{/if}
</div>

<!-- ── Side Panel ──────────────────────────────────────────────────────────── -->
{#if panelOpen}
	<!-- Mobile backdrop -->
	<div
		class="fixed inset-0 z-30 bg-black/40 lg:hidden"
		onclick={closePanel}
		aria-hidden="true"
	></div>
{/if}

<div
	class={[
		'fixed top-0 right-0 h-full w-full max-w-[600px] bg-background border-l shadow-xl z-40',
		'flex flex-col transition-transform duration-200 ease-out',
		panelOpen ? 'translate-x-0' : 'translate-x-full'
	].join(' ')}
	aria-label="Departman formu"
>
	<!-- Panel Header -->
	<div class="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
		<div class="flex items-center gap-2.5">
			<div class="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
				<Layers class="w-4 h-4 text-indigo-600" />
			</div>
			<div>
				<div class="font-semibold text-sm">{editingDept ? 'Departmanı Düzenle' : 'Yeni Departman'}</div>
				<div class="text-xs text-muted-foreground">{editingDept ? editingDept.name : 'Departman bilgilerini girin'}</div>
			</div>
		</div>
		<Button variant="ghost" size="icon" onclick={closePanel} aria-label="Kapat">
			<X class="w-4 h-4" />
		</Button>
	</div>

	<!-- Panel Body -->
	<div class="flex-1 overflow-y-auto px-6 py-5 space-y-7">

		<!-- ① Temel Bilgiler -->
		<section class="space-y-4">
			<div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground tracking-widest uppercase">
				<span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-[10px]">1</span>
				Temel Bilgiler
			</div>

			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
				<div class="space-y-1.5 sm:col-span-2">
					<label class="text-sm font-medium" for="dept-name">Departman Adı <span class="text-destructive">*</span></label>
					<Input id="dept-name" bind:value={form.name} placeholder="Yazılım Geliştirme" autocomplete="off" />
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="dept-slug">Slug</label>
					<Input id="dept-slug" bind:value={form.slug} placeholder="yazilim-gelistirme" autocomplete="off" class="font-mono text-xs" />
					<p class="text-xs text-muted-foreground">Otomatik oluşturulur</p>
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="dept-status">Durum</label>
					<select
						id="dept-status"
						bind:value={form.status}
						class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
					>
						<option value="Active">Aktif</option>
						<option value="Inactive">Pasif</option>
					</select>
				</div>

				<div class="space-y-1.5 sm:col-span-2">
					<label class="text-sm font-medium" for="dept-desc">Açıklama</label>
					<textarea
						id="dept-desc"
						class="flex min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y"
						bind:value={form.description}
						placeholder="Departmanın sorumluluklarını kısaca açıklayın..."
					></textarea>
				</div>
			</div>
		</section>

		<!-- ② Hedefler -->
		<section class="space-y-4">
			<div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground tracking-widest uppercase">
				<span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-[10px]">2</span>
				Departman Hedefleri
			</div>

			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="dept-goals">Hedefler / OKR</label>
				<textarea
					id="dept-goals"
					class="flex min-h-[140px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y font-mono text-xs leading-relaxed"
					bind:value={form.goals}
					placeholder="Her satıra bir hedef yazın:&#10;Q2 sonuna kadar CI/CD pipeline otomasyonunu tamamlamak&#10;Kod kalitesi metriklerini %90 üzerinde tutmak&#10;..."
				></textarea>
				<p class="text-xs text-muted-foreground">Her satır ayrı bir hedef olarak sayılır • {goalCount(form.goals)} hedef</p>
			</div>
		</section>

		<!-- ③ Politikalar -->
		<section class="space-y-4">
			<div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground tracking-widest uppercase">
				<span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-[10px]">3</span>
				Departman Politikaları
			</div>

			<!-- Existing policies -->
			{#if form.policies.length > 0}
				<div class="space-y-1.5">
					{#each form.policies as policy, i (policy)}
						<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/60 border border-border/50 group/policy">
							<ShieldCheck class="w-3.5 h-3.5 text-emerald-600 flex-shrink-0" />
							<span class="text-sm flex-1 truncate">{policy}</span>
							<button
								type="button"
								onclick={() => removePolicy(policy)}
								class="text-muted-foreground hover:text-destructive transition-colors flex-shrink-0 opacity-0 group-hover/policy:opacity-100"
								aria-label="Kaldır"
							>
								<X class="w-3.5 h-3.5" />
							</button>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Add policy -->
			<div class="flex gap-2">
				<Input
					bind:value={newPolicyInput}
					placeholder="Yeni politika ekle..."
					onkeydown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addPolicy(); } }}
					class="flex-1"
				/>
				<Button variant="outline" onclick={addPolicy} disabled={!newPolicyInput.trim()}>
					<Plus class="w-3.5 h-3.5" />
					Ekle
				</Button>
			</div>

			{#if form.policies.length === 0}
				<p class="text-xs text-muted-foreground">Henüz politika eklenmedi. Bu departmana bağlı tüm ajanlar bu politikalara tabi olacaktır.</p>
			{/if}
		</section>

	</div>

	<!-- Panel Footer -->
	<div class="border-t px-6 py-4 flex gap-3 justify-end flex-shrink-0 bg-background">
		<Button variant="outline" onclick={closePanel}>İptal</Button>
		<Button onclick={saveDepartment} disabled={!form.name || !form.slug}>
			{editingDept ? 'Güncelle' : 'Oluştur'}
		</Button>
	</div>
</div>

<!-- ── Delete Confirmation ─────────────────────────────────────────────────── -->
{#if showDeleteDialog}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 animate-backdrop"
		onclick={() => { showDeleteDialog = false; deleteTarget = null; }}
		aria-hidden="true"
	>
		<div
			class="bg-background w-full max-w-sm rounded-xl border p-6 shadow-lg mx-4 animate-dialog"
			onclick={(e) => e.stopPropagation()}
			role="dialog"
			aria-modal="true"
			aria-label="Departmanı Sil"
		>
			<h2 class="font-display text-xl tracking-tight">Departmanı Sil</h2>
			<p class="text-sm text-muted-foreground mt-1">
				<strong class="text-foreground">{deleteTarget?.name}</strong> departmanını kalıcı olarak silmek istediğinize emin misiniz?
				Bu işlem geri alınamaz.
			</p>
			<div class="flex gap-3 justify-end mt-5">
				<Button variant="outline" onclick={() => { showDeleteDialog = false; deleteTarget = null; }}>İptal</Button>
				<Button variant="destructive" onclick={confirmDelete}>Sil</Button>
			</div>
		</div>
	</div>
{/if}
