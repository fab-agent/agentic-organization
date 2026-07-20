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
		Loader,
		ChevronRight,
	} from '@lucide/svelte';
	import { departments as deptApi, type Department } from '$lib/api/departments';
	import { policiesApi, type Policy } from '$lib/api/policies';
	import { companyStore } from '$lib/stores/company.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import YapiTabs from '$lib/components/ui/yapi-tabs.svelte';

	// ── State ─────────────────────────────────────────────────────────────────
	let departments: Department[] = $state([]);
	let companyPolicies: Policy[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);

	async function loadDepartments() {
		try {
			loading = true;
			error = null;
			[departments, companyPolicies] = await Promise.all([
				deptApi.list(companyStore.active?.id),
				companyStore.active?.id
					? policiesApi.list({ company_id: companyStore.active.id })
					: Promise.resolve([]),
			]);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	onMount(loadDepartments);

	$effect(() => {
		if (companyStore.active) loadDepartments();
	});

	// ── Derived stats ──────────────────────────────────────────────────────────
	const activeDepts = $derived(departments.filter((d) => d.status === 'Active').length);
	const rootDepts = $derived(departments.filter((d) => !d.parent_id));
	const subDepts = $derived(departments.filter((d) => !!d.parent_id));

	// Policy lists by scope
	const companyLevelPolicies = $derived(companyPolicies.filter(p => p.scope === 'company'));
	const deptLevelPolicies = $derived(companyPolicies.filter(p => p.scope === 'department'));

	// ── Panel state ───────────────────────────────────────────────────────────
	let panelOpen    = $state(false);
	let saving       = $state(false);
	let editingDept: Department | null = $state(null);

	type FormData = {
		name: string;
		slug: string;
		parent_id: string | null;
		description: string;
		goals: string;
		policyIds: string[];   // selected Policy IDs (replaces free-text policies)
		status: 'Active' | 'Inactive';
	};

	let form: FormData = $state({
		name: '',
		slug: '',
		parent_id: null,
		description: '',
		goals: '',
		policyIds: [],
		status: 'Active'
	});

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

	function togglePolicy(policyId: string) {
		if (form.policyIds.includes(policyId)) {
			form.policyIds = form.policyIds.filter((id) => id !== policyId);
		} else {
			form.policyIds = [...form.policyIds, policyId];
		}
	}

	function openCreate() {
		editingDept = null;
		form = { name: '', slug: '', parent_id: null, description: '', goals: '', policyIds: [], status: 'Active' };
		panelOpen = true;
	}

	function openEdit(dept: Department) {
		editingDept = dept;
		form = {
			name: dept.name,
			slug: dept.slug,
			parent_id: dept.parent_id,
			description: dept.description ?? '',
			goals: dept.goals ?? '',
			policyIds: [...(dept.policy_ids ?? [])],
			status: dept.status,
		};
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
			let saved: Department;
			if (editingDept) {
				saved = await deptApi.update(editingDept.id, {
					name: form.name, slug: form.slug,
					parent_id: form.parent_id,
					description: form.description || null,
					goals: form.goals || null,
					status: form.status,
				});
				// Set policy links separately
				saved = await deptApi.setPolicies(editingDept.id, form.policyIds);
				departments = departments.map((d) => d.id === saved.id ? saved : d);
			} else {
				saved = await deptApi.create({
					name: form.name, slug: form.slug,
					parent_id: form.parent_id,
					description: form.description || null,
					goals: form.goals || null,
					status: form.status,
				}, companyStore.active?.id);
				if (form.policyIds.length) {
					saved = await deptApi.setPolicies(saved.id, form.policyIds);
				}
				departments = [...departments, saved];
			}
			closePanel();
		} catch (e) {
			alert((e as Error).message);
		} finally {
			saving = false;
		}
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

	// Available parents: exclude self and descendants
	const availableParents = $derived(
		editingDept
			? departments.filter((d) => d.id !== editingDept!.id && d.parent_id !== editingDept!.id)
			: departments
	);
</script>

<svelte:head>
	<title>Departmanlar • fab.engineering</title>
</svelte:head>

<div class="space-y-6">

	<YapiTabs />

	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">{t('dept_title')}</h1>
			<p class="text-muted-foreground mt-1">{t('dept_subtitle')}</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="h-4 w-4" />
			{t('dept_new')}
		</Button>
	</div>

	<!-- Stats -->
	<div class="grid grid-cols-3 gap-4">
		<div class="rounded-xl border bg-card p-4">
			<div class="text-2xl font-bold">{departments.length}</div>
			<div class="text-xs text-muted-foreground mt-0.5">{t('dept_stat_total')}</div>
		</div>
		<div class="rounded-xl border bg-card p-4">
			<div class="text-2xl font-bold text-emerald-600">{activeDepts}</div>
			<div class="text-xs text-muted-foreground mt-0.5">{t('dept_stat_active')}</div>
		</div>
		<div class="rounded-xl border bg-card p-4">
			<div class="text-2xl font-bold text-indigo-600">{subDepts.length}</div>
			<div class="text-xs text-muted-foreground mt-0.5">{t('dept_stat_sub')}</div>
		</div>
	</div>

	<!-- Error -->
	{#if error}
		<div class="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 flex items-center gap-2 text-sm text-destructive">
			<AlertCircle class="w-4 h-4 flex-shrink-0" />
			{error}
			<button onclick={loadDepartments} class="ml-auto underline text-xs">{t('retry')}</button>
		</div>
	{/if}

	<!-- Table or Empty State -->
	{#if loading}
		<div class="rounded-xl border bg-card flex items-center justify-center py-20 gap-2 text-muted-foreground">
			<Loader class="w-4 h-4 animate-spin" />
			<span class="text-sm">{t('loading')}</span>
		</div>
	{:else if departments.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
				<Layers class="w-6 h-6 text-muted-foreground" />
			</div>
			<div>
				<p class="font-medium">{t('dept_empty')}</p>
				<p class="text-sm text-muted-foreground mt-1">{t('dept_empty_subtitle')}</p>
			</div>
			<Button onclick={openCreate} size="sm" class="mt-2">
				<Plus class="h-4 w-4" />
				{t('dept_new')}
			</Button>
		</div>
	{:else}
		<div class="rounded-xl border bg-card overflow-hidden">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b bg-muted/50 text-left text-sm font-medium text-muted-foreground">
						<th class="h-12 px-4">{t('dept_col_dept')}</th>
						<th class="h-12 px-4 hidden sm:table-cell">{t('dept_col_parent')}</th>
						<th class="h-12 px-4 hidden md:table-cell">{t('dept_col_goal')}</th>
						<th class="h-12 px-4 hidden lg:table-cell">{t('dept_col_policy')}</th>
						<th class="h-12 px-4">{t('status')}</th>
						<th class="h-12 w-[90px] px-4 text-right">{t('dept_col_action')}</th>
					</tr>
				</thead>
				<tbody class="divide-y">
					{#each departments as dept (dept.id)}
						<tr class="hover:bg-muted/30 transition-colors group">
							<!-- Dept name + description -->
							<td class="px-4 py-3">
								<div class="flex items-center gap-2.5">
									<div class="w-8 h-8 rounded-lg {dept.parent_id ? 'bg-violet-100' : 'bg-indigo-100'} flex items-center justify-center flex-shrink-0">
										<Layers class="w-4 h-4 {dept.parent_id ? 'text-violet-600' : 'text-indigo-600'}" />
									</div>
									<div class="min-w-0">
										<div class="font-medium truncate flex items-center gap-1">
											{#if dept.parent_id}
												<span class="text-muted-foreground">↳</span>
											{/if}
											{dept.name}
										</div>
										<div class="text-xs text-muted-foreground font-mono">/{dept.slug}</div>
									</div>
								</div>
							</td>

							<!-- Parent -->
							<td class="px-4 py-3 hidden sm:table-cell">
								{#if dept.parent_name}
									<div class="flex items-center gap-1 text-muted-foreground text-xs">
										<ChevronRight class="w-3 h-3" />
										<span>{dept.parent_name}</span>
									</div>
								{:else}
									<span class="text-xs text-muted-foreground/50">—</span>
								{/if}
							</td>

							<!-- Goal count -->
							<td class="px-4 py-3 hidden md:table-cell">
								<div class="flex items-center gap-1.5 text-muted-foreground">
									<Target class="w-3.5 h-3.5 flex-shrink-0" />
									<span>{goalCount(dept.goals)} {t('dept_goal_count')}</span>
								</div>
							</td>

							<!-- Policy count -->
							<td class="px-4 py-3 hidden lg:table-cell">
								<div class="flex items-center gap-1.5 text-muted-foreground">
									<ShieldCheck class="w-3.5 h-3.5 flex-shrink-0" />
									<span>{dept.policies.length} {t('dept_policy_count')}</span>
								</div>
							</td>

							<!-- Status -->
							<td class="px-4 py-3">
								<Badge variant={dept.status === 'Active' ? 'default' : 'secondary'}>
									{dept.status === 'Active' ? t('dept_active') : t('dept_inactive')}
								</Badge>
							</td>

							<!-- Actions -->
							<td class="px-4 py-3">
								<div class="flex justify-end gap-1">
									<Button
										variant="ghost"
										size="icon"
										onclick={() => openEdit(dept)}
										aria-label={t('edit')}
									>
										<Pencil class="h-4 w-4" />
									</Button>
									<Button
										variant="ghost"
										size="icon"
										onclick={() => requestDelete(dept)}
										aria-label={t('delete')}
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
	aria-label={t('dept_title')}
>
	<!-- Panel Header -->
	<div class="flex items-center justify-between px-6 py-4 border-b flex-shrink-0">
		<div class="flex items-center gap-2.5">
			<div class="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
				<Layers class="w-4 h-4 text-indigo-600" />
			</div>
			<div>
				<div class="font-semibold text-sm">{editingDept ? t('dept_edit_title') : t('dept_create_title')}</div>
				<div class="text-xs text-muted-foreground">{editingDept ? editingDept.name : t('dept_form_subtitle')}</div>
			</div>
		</div>
		<Button variant="ghost" size="icon" onclick={closePanel} aria-label={t('close')}>
			<X class="w-4 h-4" />
		</Button>
	</div>

	<!-- Panel Body -->
	<div class="flex-1 overflow-y-auto px-6 py-5 space-y-7">

		<!-- ① Temel Bilgiler -->
		<section class="space-y-4">
			<div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground tracking-widest uppercase">
				<span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-[10px]">1</span>
				{t('dept_basic_info')}
			</div>

			<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
				<div class="space-y-1.5 sm:col-span-2">
					<label class="text-sm font-medium" for="dept-name">{t('dept_name_label')} <span class="text-destructive">*</span></label>
					<Input id="dept-name" bind:value={form.name} placeholder={t('dept_name_ph')} autocomplete="off" />
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="dept-slug">{t('dept_slug_label')}</label>
					<Input id="dept-slug" bind:value={form.slug} placeholder="yazilim-gelistirme" autocomplete="off" class="font-mono text-xs" />
					<p class="text-xs text-muted-foreground">{t('dept_slug_hint')}</p>
				</div>

				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="dept-status">{t('dept_status_label')}</label>
					<select
						id="dept-status"
						bind:value={form.status}
						class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
					>
						<option value="Active">{t('dept_active')}</option>
						<option value="Inactive">{t('dept_inactive')}</option>
					</select>
				</div>

				<div class="space-y-1.5 sm:col-span-2">
					<label class="text-sm font-medium" for="dept-parent">{t('dept_parent_label')}</label>
					<select
						id="dept-parent"
						bind:value={form.parent_id}
						class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
					>
						<option value={null}>{t('dept_parent_none')}</option>
						{#each availableParents as parent (parent.id)}
							<option value={parent.id}>{parent.name}</option>
						{/each}
					</select>
					<p class="text-xs text-muted-foreground">{t('dept_parent_hint')}</p>
				</div>

				<div class="space-y-1.5 sm:col-span-2">
					<label class="text-sm font-medium" for="dept-desc">{t('dept_desc_label')}</label>
					<textarea
						id="dept-desc"
						class="flex min-h-[72px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y"
						bind:value={form.description}
						placeholder={t('dept_desc_placeholder')}
					></textarea>
				</div>
			</div>
		</section>

		<!-- ② Hedefler -->
		<section class="space-y-4">
			<div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground tracking-widest uppercase">
				<span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-[10px]">2</span>
				{t('dept_goals_section')}
			</div>

			<div class="space-y-1.5">
				<label class="text-sm font-medium" for="dept-goals">{t('dept_goals_label')}</label>
				<textarea
					id="dept-goals"
					class="flex min-h-[140px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y font-mono text-xs leading-relaxed"
					bind:value={form.goals}
					placeholder={t('dept_goals_ph')}
				></textarea>
				<p class="text-xs text-muted-foreground">{t('dept_goals_hint')} • {goalCount(form.goals)} {t('dept_goal_count')}</p>
			</div>
		</section>

		<!-- ③ Politikalar -->
		<section class="space-y-3">
			<div class="flex items-center gap-2 text-xs font-semibold text-muted-foreground tracking-widest uppercase">
				<span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center font-bold text-[10px]">3</span>
				{t('dept_policies_section')}
			</div>

			<!-- Şirket politikaları — kilitli, her zaman aktif -->
			{#if companyLevelPolicies.length > 0}
				<div class="mb-2">
					<div class="text-xs font-medium text-muted-foreground mb-1.5">{t('dept_company_policies')} <span class="text-[10px] bg-muted px-1.5 py-0.5 rounded ml-1">{t('dept_always_active')}</span></div>
					<div class="space-y-1">
						{#each companyLevelPolicies as policy (policy.id)}
							<div class="flex items-center gap-2.5 px-3 py-2 rounded-xl border border-border/50 bg-muted/30 opacity-70 cursor-not-allowed">
								<div class="flex-shrink-0 w-4 h-4 rounded border-2 border-emerald-400 bg-emerald-500 flex items-center justify-center">
									<ShieldCheck class="w-3 h-3 text-white" />
								</div>
								<span class="text-sm font-medium truncate text-muted-foreground">{policy.name}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Bölüm politikaları — seçilebilir -->
			{#if deptLevelPolicies.length === 0}
				<p class="text-xs text-muted-foreground italic">
					{t('dept_no_dept_policies_pre')}
					<a href="/policies" class="underline text-primary">{t('nav_policies')}</a>{t('dept_no_dept_policies_suf')}
				</p>
			{:else}
				<p class="text-xs text-muted-foreground mb-1">{t('dept_select_policies')}</p>
				<div class="space-y-1.5 max-h-56 overflow-y-auto pr-1">
					{#each deptLevelPolicies as policy (policy.id)}
						{@const selected = form.policyIds.includes(policy.id)}
						<button
							type="button"
							onclick={() => togglePolicy(policy.id)}
							class="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-xl border transition-colors text-left
								{selected
									? 'bg-emerald-50 border-emerald-300 text-emerald-900'
									: 'bg-background border-border hover:bg-muted/50 text-foreground'}"
						>
							<div class="flex-shrink-0 w-4 h-4 rounded border-2 flex items-center justify-center transition-colors
								{selected ? 'bg-emerald-500 border-emerald-500' : 'border-muted-foreground/40'}">
								{#if selected}
									<ShieldCheck class="w-3 h-3 text-white" />
								{/if}
							</div>
							<div class="min-w-0 flex-1">
								<div class="text-sm font-medium truncate">{policy.name}</div>
							</div>
						</button>
					{/each}
				</div>
				{#if form.policyIds.length > 0}
					<p class="text-xs text-muted-foreground">{form.policyIds.length} {t('dept_policies_selected')}</p>
				{/if}
			{/if}
		</section>

	</div>

	<!-- Panel Footer -->
	<div class="border-t px-6 py-4 flex gap-3 justify-end flex-shrink-0 bg-background">
		<Button variant="outline" onclick={closePanel}>{t('cancel')}</Button>
		<Button onclick={saveDepartment} disabled={saving || !form.name || !form.slug}>
			{saving ? t('saving') : editingDept ? t('update') : t('create')}
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
			aria-label={t('dept_delete_title')}
		>
			<h2 class="font-display text-xl tracking-tight">{t('dept_delete_title')}</h2>
			<p class="text-sm text-muted-foreground mt-1">
				<strong class="text-foreground">{deleteTarget?.name}</strong> {t('dept_delete_confirm')}
			</p>
			<div class="flex gap-3 justify-end mt-5">
				<Button variant="outline" onclick={() => { showDeleteDialog = false; deleteTarget = null; }}>{t('cancel')}</Button>
				<Button variant="destructive" onclick={confirmDelete}>{t('delete')}</Button>
			</div>
		</div>
	</div>
{/if}
