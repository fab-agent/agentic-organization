<script lang="ts">
	import { onMount } from 'svelte';
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Dialog from '$lib/components/ui/dialog.svelte';
	import Table from '$lib/components/ui/table.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import {
		Plus, Pencil, Trash2, Users, Bot, Loader, Mail,
		ShieldCheck, UserCheck, X, Building, User,
		BrainCircuit, MessageSquare, Clock, ChevronLeft,
	} from '@lucide/svelte';
	import { personnel as personnelApi, type PersonnelItem, type PersonnelCreate } from '$lib/api/personnel';
	import { departments as deptApi, type Department } from '$lib/api/departments';
	import { companyStore } from '$lib/stores/company.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { invitePersonnel } from '$lib/api/client';
	import { sessionsApi, type Session, type AgentMemory } from '$lib/api/sessions';
	import { t } from '$lib/i18n/index.svelte';

	let people: PersonnelItem[] = $state([]);
	let depts: Department[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let saving = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			[people, depts] = await Promise.all([
				personnelApi.list({ company_id: companyStore.active?.id, type: 'human' }),
				deptApi.list(companyStore.active?.id),
			]);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	onMount(load);
	$effect(() => { if (companyStore.active) load(); });

	function slugify(text: string): string {
		return text
			.toLowerCase()
			.replace(/ğ/g, 'g').replace(/ş/g, 's').replace(/ı/g, 'i')
			.replace(/ö/g, 'o').replace(/ü/g, 'u').replace(/ç/g, 'c')
			.replace(/[^a-z0-9\s-]/g, '').trim()
			.replace(/\s+/g, '-').replace(/-+/g, '-');
	}

	// ── Side panel: view / edit / create ─────────────────────────────────────
	type PanelMode = 'view' | 'edit' | 'create';
	let panelMode   = $state<PanelMode | null>(null);
	let selectedPerson = $state<PersonnelItem | null>(null);
	let panelSessions  = $state<Session[]>([]);
	let panelMemories  = $state<AgentMemory[]>([]);
	let panelLoading   = $state(false);

	let form = $state<PersonnelCreate & { title: string; email: string }>({
		name: '', slug: '', title: '', role: '',
		type: 'human', department_id: '', manager_id: '', email: '',
	});

	$effect(() => {
		if (panelMode === 'create') {
			form.slug = slugify(form.name);
		}
	});

	function openView(p: PersonnelItem) {
		selectedPerson = p;
		panelMode = 'view';
		panelSessions = [];
		panelMemories = [];
		panelLoading = true;
		Promise.all([
			sessionsApi.list({ personnel_id: p.id }),
			sessionsApi.memories(p.id),
		]).then(([s, m]) => {
			panelSessions = s;
			panelMemories = m;
		}).catch(() => {}).finally(() => { panelLoading = false; });
	}

	function openEdit(p: PersonnelItem) {
		selectedPerson = p;
		form = {
			name: p.name, slug: p.slug, title: p.title ?? '',
			role: p.role ?? '', type: p.type,
			department_id: p.department_id ?? '',
			manager_id: p.manager_id ?? '',
			email: (p as any).email ?? '',
		};
		panelMode = 'edit';
	}

	function openCreate() {
		selectedPerson = null;
		form = { name: '', slug: '', title: '', role: '', type: 'human', department_id: '', manager_id: '', email: '' };
		panelMode = 'create';
	}

	function closePanel() { panelMode = null; selectedPerson = null; }

	async function save() {
		if (!form.name.trim()) return;
		saving = true;
		try {
			const payload: PersonnelCreate = {
				name: form.name, slug: form.slug,
				title: form.title || undefined, role: form.role || undefined,
				type: form.type,
				email: form.email || undefined,
				department_id: form.department_id || undefined,
				manager_id: form.manager_id || undefined,
			};
			if (panelMode === 'edit' && selectedPerson) {
				const updated = await personnelApi.update(selectedPerson.id, payload);
				people = people.map(p => p.id === selectedPerson!.id ? updated : p);
				selectedPerson = updated;
				panelMode = 'view';
			} else {
				const created = await personnelApi.create(payload);
				people = [...people, created];
				closePanel();
			}
		} catch (e) {
			alert((e as Error).message);
		} finally {
			saving = false;
		}
	}

	// ── Delete ────────────────────────────────────────────────────────────────
	let deleteTarget: PersonnelItem | null = $state(null);
	let showDeleteDialog = $state(false);
	let deleting = $state(false);

	async function confirmDelete() {
		if (!deleteTarget) return;
		deleting = true;
		try {
			await personnelApi.delete(deleteTarget.id);
			people = people.filter(p => p.id !== deleteTarget!.id);
			deleteTarget = null;
			showDeleteDialog = false;
			closePanel();
		} catch (e) {
			alert((e as Error).message);
		} finally {
			deleting = false;
		}
	}

	// ── Invite ────────────────────────────────────────────────────────────────
	const ROLE_OPTIONS = [
		{ value: 'executive',   label: 'Yönetici (Executive)' },
		{ value: 'dept_head',   label: 'Bölüm Yöneticisi' },
		{ value: 'agent_owner', label: 'Ajan Sorumlusu' },
		{ value: 'user',        label: 'Kullanıcı' },
	];

	let inviteTarget: PersonnelItem | null = $state(null);
	let showInviteDialog = $state(false);
	let inviteRole = $state('user');
	let inviting = $state(false);
	let inviteError = $state('');
	let inviteDone = $state(false);

	function openInvite(p: PersonnelItem) {
		inviteTarget = p;
		inviteRole = 'user';
		inviteError = '';
		inviteDone = false;
		showInviteDialog = true;
	}

	async function confirmInvite() {
		if (!inviteTarget) return;
		inviting = true;
		inviteError = '';
		try {
			await invitePersonnel(inviteTarget.id, inviteRole);
			inviteDone = true;
			people = people.map(p =>
				p.id === inviteTarget!.id ? { ...p, has_user: true } as any : p
			);
			setTimeout(() => { showInviteDialog = false; inviteTarget = null; }, 2000);
		} catch (e: any) {
			inviteError = e?.message ?? 'Davet gönderilemedi';
		} finally {
			inviting = false;
		}
	}

	// ── Permissions ───────────────────────────────────────────────────────────
	const activeCompanyId = $derived(companyStore.active?.id ?? '');
	const canManage = $derived(authStore.can(activeCompanyId, 'dept_head'));

	// ── Stats ─────────────────────────────────────────────────────────────────
	const humanCount = $derived(people.filter(p => p.type === 'human').length);
	const agentCount = $derived(people.filter(p => p.type === 'agent').length);
</script>

<svelte:head>
	<title>Personel • fab.engineering</title>
</svelte:head>

<div class="space-y-6">
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">{t('personnel_title')}</h1>
			<p class="text-muted-foreground mt-1">
				{#if !loading}
					{humanCount} {t('personnel_type_human')} · {agentCount} {t('personnel_type_agent')}
				{:else}
					{t('loading')}
				{/if}
			</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="h-4 w-4" />
			{t('personnel_new')}
		</Button>
	</div>

	{#if loading}
		<div class="flex items-center justify-center py-20 text-muted-foreground gap-2">
			<Loader class="w-5 h-5 animate-spin" />
			<span class="text-sm">{t('loading')}</span>
		</div>
	{:else if error}
		<div class="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
			{error}
		</div>
	{:else if people.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
				<Users class="w-6 h-6 text-muted-foreground" />
			</div>
			<div>
				<p class="font-medium">{t('personnel_empty')}</p>
				<p class="text-sm text-muted-foreground mt-1">{t('personnel_empty_subtitle')}</p>
			</div>
			<Button onclick={openCreate} size="sm" class="mt-2">
				<Plus class="h-4 w-4" />
				{t('personnel_new')}
			</Button>
		</div>
	{:else}
		<div class="rounded-xl border bg-card overflow-hidden">
			<Table>
				<thead>
					<tr class="border-b bg-muted/50 text-left text-sm font-medium text-muted-foreground">
						<th class="h-12 px-4">{t('personnel_col_personnel')}</th>
						<th class="h-12 px-4 hidden md:table-cell">{t('personnel_col_dept')}</th>
						<th class="h-12 px-4 hidden lg:table-cell">{t('personnel_col_manager')}</th>
						<th class="h-12 px-4">{t('personnel_col_type')}</th>
						<th class="h-12 px-4 hidden xl:table-cell">{t('personnel_col_platform')}</th>
						<th class="h-12 w-[120px] px-4 text-right">{t('personnel_col_actions')}</th>
					</tr>
				</thead>
				<tbody class="divide-y">
					{#each people as person (person.id)}
						<tr class="hover:bg-muted/30 transition-colors cursor-pointer {selectedPerson?.id === person.id && panelMode === 'view' ? 'bg-muted/40' : ''}"
							onclick={(e) => { if ((e.target as HTMLElement).closest('button')) return; openView(person); }}>
							<td class="px-4 py-3">
								<div class="flex items-center gap-3">
									<div class="h-9 w-9 rounded-lg ring-1 ring-border flex-shrink-0 bg-muted flex items-center justify-center">
										{#if person.type === 'agent'}
											<Bot class="w-4 h-4 text-muted-foreground" />
										{:else}
											<span class="text-sm font-semibold text-muted-foreground">{person.name.charAt(0)}</span>
										{/if}
									</div>
									<div>
										<div class="font-medium">{person.name}</div>
										<div class="text-xs text-muted-foreground">{person.title ?? person.role ?? ''}</div>
									</div>
								</div>
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden md:table-cell">
								{person.department_name ?? '—'}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell">
								{person.manager_name ?? '—'}
							</td>
							<td class="px-4 py-3">
								{#if person.type === 'agent'}
									{#if person.agent_config}
										<Badge variant={person.agent_config.status === 'active' ? 'default' : person.agent_config.status === 'draft' ? 'secondary' : 'outline'}>
											{person.agent_config.status === 'active' ? t('status_active') : person.agent_config.status === 'draft' ? t('status_draft') : t('status_inactive')}
										</Badge>
									{:else}
										<Badge variant="outline">{t('personnel_type_agent')}</Badge>
									{/if}
								{:else}
									<Badge variant="secondary">{t('personnel_type_human')}</Badge>
								{/if}
							</td>
							<td class="px-4 py-3 hidden xl:table-cell">
								{#if person.type === 'human'}
									{#if (person as any).has_user}
										<span class="inline-flex items-center gap-1.5 text-xs text-emerald-600 font-medium">
											<UserCheck class="w-3.5 h-3.5" />
											{t('personnel_status_active')}
										</span>
									{:else if (person as any).email}
										<span class="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
											<Mail class="w-3.5 h-3.5" />
											{t('personnel_not_invited')}
										</span>
									{:else}
										<span class="text-xs text-muted-foreground">—</span>
									{/if}
								{:else}
									<span class="text-xs text-muted-foreground">—</span>
								{/if}
							</td>
							<td class="px-4 py-3">
								<div class="flex justify-end gap-1">
									{#if person.type === 'human' && canManage && (person as any).email && !(person as any).has_user}
										<Button
											variant="ghost" size="icon"
											onclick={() => openInvite(person)}
											aria-label={t('personnel_invite')}
											class="text-primary hover:text-primary hover:bg-primary/10"
											title={t('personnel_platform_invite')}
										>
											<Mail class="h-4 w-4" />
										</Button>
									{/if}
									<Button variant="ghost" size="icon" onclick={() => openEdit(person)} aria-label={t('edit')}>
										<Pencil class="h-4 w-4" />
									</Button>
									<Button
										variant="ghost" size="icon"
										onclick={() => { deleteTarget = person; showDeleteDialog = true; }}
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
			</Table>
		</div>
	{/if}
</div>

<!-- Invite Dialog (kept as dialog — simple confirmation flow) -->
<Dialog bind:open={showInviteDialog} label={t('personnel_invite_title')}>
	<div class="space-y-5">
		<div>
			<h2 class="font-display text-xl tracking-tight">{t('personnel_invite_title')}</h2>
			<p class="text-sm text-muted-foreground mt-1">
				<strong class="text-foreground">{inviteTarget?.name}</strong> adresine
				<strong class="text-foreground">{(inviteTarget as any)?.email}</strong> geçici şifre gönderilecek.
			</p>
		</div>

		{#if inviteDone}
			<div class="flex items-center gap-2 rounded-lg bg-emerald-50 border border-emerald-200 px-3 py-2.5 text-sm text-emerald-700">
				<UserCheck class="w-4 h-4 flex-shrink-0" />
				{t('personnel_invite_done')}
			</div>
		{:else}
			<div class="space-y-3">
				<div class="space-y-1.5">
					<label class="text-sm font-medium">{t('personnel_invite_role_label')}</label>
					<select
						class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
						bind:value={inviteRole}
					>
						{#each ROLE_OPTIONS as opt}
							<option value={opt.value}>{opt.label}</option>
						{/each}
					</select>
					<p class="text-xs text-muted-foreground">{t('personnel_invite_role_hint')}</p>
				</div>
				{#if inviteError}
					<div class="rounded-lg bg-destructive/10 border border-destructive/20 px-3 py-2 text-sm text-destructive">
						{inviteError}
					</div>
				{/if}
			</div>
			<div class="flex flex-col-reverse gap-3 pt-2 sm:flex-row sm:justify-end">
				<Button variant="outline" onclick={() => { showInviteDialog = false; inviteTarget = null; }} class="sm:w-auto">{t('cancel')}</Button>
				<Button onclick={confirmInvite} disabled={inviting} class="sm:w-auto gap-2">
					{#if inviting}
						<Loader class="w-4 h-4 animate-spin" />
						{t('sending')}
					{:else}
						<Mail class="w-4 h-4" />
						{t('personnel_invite_send')}
					{/if}
				</Button>
			</div>
		{/if}
	</div>
</Dialog>

<!-- Delete Dialog -->
<Dialog bind:open={showDeleteDialog} label={t('personnel_delete_title')}>
	<div class="space-y-4">
		<h2 class="font-display text-xl tracking-tight">{t('personnel_delete_title')}</h2>
		<p class="text-sm text-muted-foreground">
			<strong class="text-foreground">{deleteTarget?.name}</strong> {t('personnel_delete_confirm')}
		</p>
		<div class="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
			<Button variant="outline" onclick={() => { deleteTarget = null; showDeleteDialog = false; }} class="sm:w-auto">{t('cancel')}</Button>
			<Button variant="destructive" onclick={confirmDelete} disabled={deleting} class="sm:w-auto">
				{deleting ? t('deleting') : t('delete')}
			</Button>
		</div>
	</div>
</Dialog>

<!-- ── Side Panel ────────────────────────────────────────────────────────── -->
{#if panelMode !== null}
	<div class="fixed inset-0 z-30 bg-black/30 lg:hidden" onclick={closePanel} aria-hidden="true"></div>

	<aside class="person-panel">

		<!-- Header -->
		<div class="flex items-center justify-between px-5 py-4 border-b border-border flex-shrink-0">
			{#if panelMode === 'view'}
				<div class="flex items-center gap-3">
					<div class="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center ring-1 ring-border flex-shrink-0">
						<span class="text-base font-bold text-primary">{selectedPerson?.name.charAt(0)}</span>
					</div>
					<div>
						<div class="font-semibold text-base leading-tight">{selectedPerson?.name}</div>
						<div class="text-sm text-muted-foreground mt-0.5">{selectedPerson?.title ?? selectedPerson?.role ?? '—'}</div>
					</div>
				</div>
			{:else}
				<div class="flex items-center gap-2">
					{#if panelMode === 'edit'}
						<button class="text-muted-foreground hover:text-foreground" onclick={() => (selectedPerson ? openView(selectedPerson) : closePanel())} aria-label="Geri">
							<ChevronLeft class="w-5 h-5" />
						</button>
					{/if}
					<span class="font-semibold text-base">
						{panelMode === 'edit' ? 'Personeli Düzenle' : 'Yeni Personel'}
					</span>
				</div>
			{/if}
			<button class="text-muted-foreground hover:text-foreground ml-2 flex-shrink-0" onclick={closePanel}>
				<X class="w-5 h-5" />
			</button>
		</div>

		<!-- Body -->
		<div class="flex-1 overflow-y-auto">

			<!-- ── VIEW MODE ── -->
			{#if panelMode === 'view' && selectedPerson}
				<div class="p-5 space-y-5">
					<!-- Info rows -->
					<div class="space-y-3">
						<div class="flex items-center gap-3 text-sm">
							<Building class="w-4 h-4 text-muted-foreground flex-shrink-0" />
							<span class="text-muted-foreground w-24 flex-shrink-0">Departman</span>
							<span class="font-medium">{selectedPerson.department_name ?? '—'}</span>
						</div>
						<div class="flex items-center gap-3 text-sm">
							<User class="w-4 h-4 text-muted-foreground flex-shrink-0" />
							<span class="text-muted-foreground w-24 flex-shrink-0">Yönetici</span>
							<span class="font-medium">{selectedPerson.manager_name ?? '—'}</span>
						</div>
						{#if (selectedPerson as any).email}
							<div class="flex items-center gap-3 text-sm">
								<Mail class="w-4 h-4 text-muted-foreground flex-shrink-0" />
								<span class="text-muted-foreground w-24 flex-shrink-0">E-posta</span>
								<span class="font-medium font-mono text-xs">{(selectedPerson as any).email}</span>
							</div>
						{/if}
						<div class="flex items-center gap-3 text-sm">
							<ShieldCheck class="w-4 h-4 text-muted-foreground flex-shrink-0" />
							<span class="text-muted-foreground w-24 flex-shrink-0">Platform</span>
							{#if (selectedPerson as any).has_user}
								<span class="inline-flex items-center gap-1.5 text-emerald-600 font-medium">
									<UserCheck class="w-3.5 h-3.5" /> Aktif kullanıcı
								</span>
							{:else if (selectedPerson as any).email}
								<span class="text-muted-foreground">Davet bekliyor</span>
							{:else}
								<span class="text-muted-foreground">E-posta yok</span>
							{/if}
						</div>
					</div>

					{#if selectedPerson.role}
						<div class="rounded-xl bg-muted/50 px-4 py-3">
							<div class="text-xs font-medium text-muted-foreground mb-1">Rol</div>
							<div class="text-sm font-medium">{selectedPerson.role}</div>
						</div>
					{/if}

					<!-- Sessions -->
					<div>
						<div class="flex items-center gap-2 mb-3">
							<MessageSquare class="w-4 h-4 text-muted-foreground" />
							<span class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Oturumlar</span>
							{#if panelLoading}
								<Loader class="w-3 h-3 animate-spin text-muted-foreground ml-auto" />
							{/if}
						</div>
						{#if panelSessions.length === 0 && !panelLoading}
							<p class="text-xs text-muted-foreground">Henüz oturum yok.</p>
						{:else}
							<div class="space-y-2">
								{#each panelSessions.slice(0, 3) as s}
									<div class="rounded-lg border border-border bg-muted/30 px-3 py-2">
										<div class="flex items-center justify-between gap-2">
											<span class="text-xs font-medium truncate">{s.title ?? 'Oturum'}</span>
											<span class="text-xs px-1.5 py-0.5 rounded-md font-medium flex-shrink-0
												{s.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-muted text-muted-foreground'}">
												{s.status === 'active' ? 'Aktif' : 'Kapalı'}
											</span>
										</div>
										<div class="flex items-center gap-1 mt-1 text-xs text-muted-foreground">
											<Clock class="w-3 h-3" />
											{new Date(s.updated_at).toLocaleDateString('tr-TR', { day:'numeric', month:'short', hour:'2-digit', minute:'2-digit' })}
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>

					<!-- Memories -->
					<div>
						<div class="flex items-center gap-2 mb-3">
							<BrainCircuit class="w-4 h-4 text-muted-foreground" />
							<span class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Uzun Dönem Hafıza</span>
						</div>
						{#if panelMemories.length === 0 && !panelLoading}
							<p class="text-xs text-muted-foreground">Henüz hafıza kaydı yok. Oturumlar kapandığında özetler burada görünür.</p>
						{:else}
							<div class="space-y-2">
								{#each panelMemories as m}
									<div class="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
										<p class="text-xs leading-relaxed">{m.summary}</p>
										<div class="flex items-center gap-1 mt-1.5 text-xs text-muted-foreground">
											<Clock class="w-3 h-3" />
											{new Date(m.created_at).toLocaleDateString('tr-TR', { day:'numeric', month:'short', year:'numeric' })}
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				</div>

			<!-- ── EDIT / CREATE MODE ── -->
			{:else if panelMode === 'edit' || panelMode === 'create'}
				<div class="p-5 space-y-4">
					<div class="grid grid-cols-2 gap-3">
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="p-name">{t('personnel_name_label')}</label>
							<Input id="p-name" bind:value={form.name} placeholder="Ahmet Yılmaz" autocomplete="off" />
						</div>
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="p-slug">{t('personnel_slug_label')}</label>
							<Input id="p-slug" bind:value={form.slug} placeholder="ahmet-yilmaz" autocomplete="off" class="font-mono text-xs" />
						</div>
					</div>

					<div class="grid grid-cols-2 gap-3">
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="p-title">{t('personnel_title_label')}</label>
							<Input id="p-title" bind:value={form.title} placeholder="Yazılım Mühendisi" autocomplete="off" />
						</div>
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="p-role">{t('personnel_role_label')}</label>
							<Input id="p-role" bind:value={form.role} placeholder="Engineer" autocomplete="off" />
						</div>
					</div>

					<div class="grid grid-cols-2 gap-3">
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="p-type">{t('personnel_type_label')}</label>
							<select id="p-type" class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" bind:value={form.type}>
								<option value="human">{t('personnel_type_human')}</option>
								<option value="agent">{t('personnel_type_agent')}</option>
							</select>
						</div>
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="p-dept">{t('personnel_dept_label')}</label>
							<select id="p-dept" class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" bind:value={form.department_id}>
								<option value="">{t('select_placeholder')}</option>
								{#each depts as d}
									<option value={d.id}>{d.name}</option>
								{/each}
							</select>
						</div>
					</div>

					<div class="space-y-1.5">
						<label class="text-sm font-medium" for="p-manager">{t('personnel_manager_label')}</label>
						<select id="p-manager" class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" bind:value={form.manager_id}>
							<option value="">{t('select_placeholder')}</option>
							{#each people.filter(p => p.type === 'human') as p}
								<option value={p.id}>{p.name}</option>
							{/each}
						</select>
					</div>

					{#if form.type === 'human'}
						<div class="space-y-1.5">
							<label class="text-sm font-medium" for="p-email">
								{t('personnel_email_label')} <span class="text-muted-foreground font-normal">{t('personnel_email_hint')}</span>
							</label>
							<Input id="p-email" type="email" bind:value={form.email} placeholder="ahmet@sirket.com" autocomplete="off" />
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Footer -->
		{#if panelMode === 'view' && canManage}
			<div class="flex gap-2 p-4 border-t border-border flex-shrink-0">
				{#if (selectedPerson as any)?.email && !(selectedPerson as any)?.has_user}
					<Button variant="outline" size="sm" class="flex-1 gap-1.5"
						onclick={() => { openInvite(selectedPerson!); }}>
						<Mail class="w-3.5 h-3.5" /> Davet Et
					</Button>
				{/if}
				<Button variant="outline" size="sm" class="flex-1 gap-1.5"
					onclick={() => openEdit(selectedPerson!)}>
					<Pencil class="w-3.5 h-3.5" /> Düzenle
				</Button>
				<Button variant="ghost" size="sm" class="text-destructive hover:text-destructive hover:bg-destructive/10 gap-1.5"
					onclick={() => { deleteTarget = selectedPerson; showDeleteDialog = true; }}>
					<Trash2 class="w-3.5 h-3.5" />
				</Button>
			</div>
		{:else if panelMode === 'edit' || panelMode === 'create'}
			<div class="flex gap-2 p-4 border-t border-border flex-shrink-0">
				<Button variant="outline" class="flex-1"
					onclick={() => (panelMode === 'edit' && selectedPerson ? openView(selectedPerson) : closePanel())}>
					{t('cancel')}
				</Button>
				<Button class="flex-1" onclick={save} disabled={!form.name.trim() || saving}>
					{saving ? t('saving') : panelMode === 'edit' ? t('update') : t('add')}
				</Button>
			</div>
		{/if}
	</aside>
{/if}

<style>
.person-panel {
	position: fixed;
	top: 0; right: 0; bottom: 0;
	width: 420px;
	max-width: 100vw;
	background: hsl(var(--card));
	border-left: 1px solid hsl(var(--border));
	box-shadow: -8px 0 32px rgba(0,0,0,0.08);
	z-index: 40;
	display: flex;
	flex-direction: column;
	animation: slideIn 0.18s cubic-bezier(0.32,0.72,0,1);
}
@keyframes slideIn {
	from { transform: translateX(100%); }
	to   { transform: translateX(0); }
}
</style>
