<script lang="ts">
	import { onMount } from 'svelte';
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import Table from '$lib/components/ui/table.svelte';
	import { Plus, Pencil, Trash2, Bot, Sparkles, X, Check, Loader, GitPullRequest } from '@lucide/svelte';
	import { personnel as personnelApi, type PersonnelItem } from '$lib/api/personnel';
	import { departments as deptApi, type Department } from '$lib/api/departments';
	import { skillsApi, type CompanySkill, type BuiltinTool } from '$lib/api/skills';
	import { policiesApi, type Policy } from '$lib/api/policies';
	import { companyStore } from '$lib/stores/company.svelte';
	import { changeRequests as crApi } from '$lib/api/change_requests';
	import { providers as providerApi, type ModelDef, type PriceTier } from '$lib/api/providers';
	import { api } from '$lib/api/client.js';
	import { t, i18n } from '$lib/i18n/index.svelte';
	import YapiTabs from '$lib/components/ui/yapi-tabs.svelte';

	// ── Dynamic models ────────────────────────────────────────────────────────
	let availableModels = $state<ModelDef[]>([]);
	let modelsLoading = $state(true);

	const TIER_LABEL: Record<PriceTier, string> = {
		low:     '$',
		medium:  '$$',
		high:    '$$$',
		premium: '$$$$',
	};
	const TIER_COLOR: Record<PriceTier, string> = {
		low:     'text-emerald-600',
		medium:  'text-amber-500',
		high:    'text-orange-500',
		premium: 'text-red-500',
	};

	function modelLabel(m: ModelDef): string {
		return m.name;
	}
	function modelTierHint(m: ModelDef): string {
		const sign = TIER_LABEL[m.tier] ?? '?';
		if (m.input_per_m != null) {
			return `${sign} · $${m.input_per_m}/1M giriş`;
		}
		return sign;
	}

	// All company policies — loaded from DB (replaces hardcoded DEPT_POLICIES)
	let companyPolicies = $state<Policy[]>([]);

	type LocalSkill = { name: string; version: string; description: string; skill_type?: string; config_json?: string };

	// Company skills (loaded from API, replaces the old hardcoded SKILL_LIBRARY)
	let companySkills = $state<CompanySkill[]>([]);

	const KEYWORD_MAP: Array<[RegExp, string[]]> = [
	];

	const SKILL_TYPES = [
		{ value: 'builtin',  label: 'Dahili',     hint: 'Platform hazır araçları' },
		{ value: 'mcp',      label: 'MCP',         hint: 'Model Context Protocol sunucusu' },
		{ value: 'http',     label: 'HTTP API',    hint: 'REST webhook veya API' },
		{ value: 'function', label: 'Fonksiyon',   hint: 'Özel Python kodu (run(args) → str)' },
		{ value: 'database', label: 'Veritabanı',  hint: 'SQL sorgu — semantik şema ile' },
	];

	// Loaded dynamically from backend — single source of truth
	let builtinTools = $state<BuiltinTool[]>([]);
	let builtinToolsLoading = $state(true);

	// ── Database list (for database skill type) ───────────────────────────────
	type DBItem = { id: string; name: string; db_type: string; status: string };
	let databases = $state<DBItem[]>([]);

	function slugify(text: string): string {
		return text.toLowerCase()
			.replace(/ğ/g,'g').replace(/ş/g,'s').replace(/ı/g,'i')
			.replace(/ö/g,'o').replace(/ü/g,'u').replace(/ç/g,'c')
			.replace(/[^a-z0-9\s-]/g,'').trim()
			.replace(/\s+/g,'-').replace(/-+/g,'-');
	}

	// ── API data ──────────────────────────────────────────────────────────────
	let agents = $state<PersonnelItem[]>([]);
	let depts = $state<Department[]>([]);
	let humanPersonnel = $state<PersonnelItem[]>([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let saving = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			[agents, depts, humanPersonnel] = await Promise.all([
				personnelApi.list({ type: 'agent', company_id: companyStore.active?.id }),
				deptApi.list(companyStore.active?.id),
				personnelApi.list({ type: 'human', company_id: companyStore.active?.id }),
			]);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	async function loadCompanySkills() {
		try {
			companySkills = await skillsApi.list(companyStore.active?.id);
		} catch {
			companySkills = [];
		}
	}

	async function loadCompanyPolicies() {
		try {
			companyPolicies = companyStore.active?.id
				? await policiesApi.list({ company_id: companyStore.active.id })
				: [];
		} catch {
			companyPolicies = [];
		}
	}

	onMount(async () => {
		load();
		loadCompanySkills();
		loadCompanyPolicies();
		try {
			availableModels = await providerApi.models();
		} catch {
			availableModels = [];
		} finally {
			modelsLoading = false;
		}
		try {
			databases = await api.get<DBItem[]>('/databases/');
		} catch {
			databases = [];
		}
		try {
			builtinTools = await skillsApi.listBuiltinTools();
		} catch {
			builtinTools = [];
		} finally {
			builtinToolsLoading = false;
		}
	});

	$effect(() => {
		if (companyStore.active) { load(); loadCompanySkills(); loadCompanyPolicies(); }
	});

	// ── Form state ─────────────────────────────────────────────────────────────
	let showPanel = $state(false);
	let editingId: string | null = $state(null);

	const emptyForm = () => ({
		name: '', slug: '', title: '',
		model: 'claude-sonnet-4-6',
		status: 'draft' as 'active' | 'draft' | 'inactive',
		department_id: '',
		responsible_id: '',
		jobDescription: '',
		selectedSkills: [] as LocalSkill[],
		selectedCompanySkillIds: [] as string[], // CompanySkill IDs linked via AgentSkillLink
		selectedAgentPolicyIds: [] as string[], // agent-specific Policy IDs
	});

	let form = $state(emptyForm());

	const selectedDept = $derived(depts.find(d => d.id === form.department_id) ?? null);
	const selectedDeptName = $derived(selectedDept?.name ?? '');
	// Policy IDs inherited from the selected department (locked, not editable per agent)
	const inheritedPolicyIds = $derived(selectedDept?.policy_ids ?? []);

	$effect(() => {
		if (editingId === null) form.slug = slugify(form.name);
	});

	function openCreate() {
		editingId = null;
		form = emptyForm();
		suggestedSkills = [];
		showPanel = true;
	}

	function openEdit(agent: PersonnelItem) {
		editingId = agent.id;
		const cfg = agent.agent_config;
		const linkedCsIds = (cfg?.company_skills ?? []).map((cs) => cs.id);
		const agentPolicyIds = cfg?.agent_policy_ids ?? [];
		form = {
			name: agent.name,
			slug: agent.slug,
			title: agent.title ?? '',
			model: cfg?.model ?? 'claude-sonnet-4-6',
			status: cfg?.status ?? 'draft',
			department_id: agent.department_id ?? '',
			responsible_id: cfg?.responsible_id ?? '',
			jobDescription: agent.role ?? '',
			selectedSkills: (cfg?.skills ?? []).map(s => ({
				name: s.name,
				version: s.version,
				description: s.description ?? '',
			})),
			selectedCompanySkillIds: linkedCsIds,
			selectedAgentPolicyIds: agentPolicyIds,
		};
		suggestedSkills = [];
		showPanel = true;
	}

	function closePanel() {
		showPanel = false;
		editingId = null;
	}

	async function saveAgent() {
		if (!form.name || !form.title) return;
		saving = true;
		try {
			const personnelPayload = {
				name: form.name,
				slug: form.slug,
				title: form.title || undefined,
				role: form.jobDescription || undefined,
				type: 'agent' as const,
				company_id: companyStore.active?.id,
				department_id: form.department_id || undefined,
			};
			const configPayload = {
				model: form.model,
				status: form.status,
				responsible_id: form.responsible_id || undefined,
			};

			if (editingId) {
				await personnelApi.update(editingId, personnelPayload);
				await personnelApi.updateAgentConfig(editingId, configPayload);
				// Sync legacy per-agent skills
				const existingSkills = agents.find(a => a.id === editingId)?.agent_config?.skills ?? [];
				for (const s of existingSkills) {
					try { await personnelApi.deleteSkill(editingId, s.id); } catch {}
				}
				for (const s of form.selectedSkills) {
					await personnelApi.addSkill(editingId, s);
				}
				// Sync CompanySkill assignments
				const agentCfgId = agents.find(a => a.id === editingId)?.agent_config?.id;
				if (agentCfgId) {
					const prevIds = ((agents.find(a => a.id === editingId)?.agent_config as any)?.company_skills ?? []).map((cs: { id: string }) => cs.id) as string[];
					for (const id of prevIds) {
						if (!form.selectedCompanySkillIds.includes(id)) {
							try { await skillsApi.unassign(id, agentCfgId); } catch {}
						}
					}
					for (const id of form.selectedCompanySkillIds) {
						if (!prevIds.includes(id)) {
							try { await skillsApi.assign(id, agentCfgId); } catch {}
						}
					}
				}
			} else {
				const created = await personnelApi.create(personnelPayload);
				const newCfg = await personnelApi.createAgentConfig(created.id, configPayload);
				for (const s of form.selectedSkills) {
					await personnelApi.addSkill(created.id, s);
				}
				// Assign CompanySkills to new agent
				const newCfgId = (newCfg as any)?.id;
				if (newCfgId) {
					for (const id of form.selectedCompanySkillIds) {
						try { await skillsApi.assign(id, newCfgId); } catch {}
					}
				}
				// Set agent-specific policies for new agent
				if (form.selectedAgentPolicyIds.length) {
					try { await personnelApi.setAgentPolicies(created.id, form.selectedAgentPolicyIds); } catch {}
				}
			}
			// Always sync agent-specific policies on update too
			if (editingId) {
				try { await personnelApi.setAgentPolicies(editingId, form.selectedAgentPolicyIds); } catch {}
			}
			await load();
			closePanel();
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

	function requestDelete(agent: PersonnelItem) { deleteTarget = agent; showDeleteDialog = true; }
	function cancelDelete() { deleteTarget = null; showDeleteDialog = false; }

	async function confirmDelete() {
		if (!deleteTarget) return;
		deleting = true;
		try {
			await personnelApi.delete(deleteTarget.id);
			agents = agents.filter(a => a.id !== deleteTarget!.id);
			cancelDelete();
		} catch (e) {
			alert((e as Error).message);
		} finally {
			deleting = false;
		}
	}

	// ── Stats ─────────────────────────────────────────────────────────────────
	const totalActive = $derived(agents.filter(a => a.agent_config?.status === 'active').length);
	const totalDraft  = $derived(agents.filter(a => a.agent_config?.status === 'draft').length);

	const STATUS_BADGE: Record<string, 'default' | 'secondary' | 'destructive'> = {
		active: 'default', draft: 'secondary', inactive: 'destructive'
	};
	const STATUS_LABEL: Record<string, string> = {
		active: 'Aktif', draft: 'Taslak', inactive: 'Pasif'
	};

	// ── Skill helpers ─────────────────────────────────────────────────────────
	function isSkillSelected(name: string): boolean {
		return form.selectedSkills.some(s => s.name === name);
	}

	function isCompanySkillSelected(id: string): boolean {
		return form.selectedCompanySkillIds.includes(id);
	}

	function toggleCompanySkill(id: string) {
		if (form.selectedCompanySkillIds.includes(id)) {
			form.selectedCompanySkillIds = form.selectedCompanySkillIds.filter(x => x !== id);
		} else {
			form.selectedCompanySkillIds = [...form.selectedCompanySkillIds, id];
		}
	}

	let customSkill = $state({
		name: '', description: '',
		skill_type: 'builtin' as string,
		mcp_url: '', mcp_transport: 'sse', mcp_auth_type: 'none', mcp_auth_value: '',
		http_url: '', http_method: 'POST',
		builtin_fn: 'web_search',
		fn_code: '',
		db_id: '',
	});

	function addCustomSkill() {
		const { name, description, skill_type } = customSkill;
		if (!name.trim()) return;
		if (isSkillSelected(name)) return;

		let config_json: string | undefined;
		if (skill_type === 'builtin') {
			config_json = JSON.stringify({ function_name: customSkill.builtin_fn });
		} else if (skill_type === 'mcp') {
			config_json = JSON.stringify({
				url: customSkill.mcp_url,
				transport: customSkill.mcp_transport,
				auth_type: customSkill.mcp_auth_type,
				auth_value: customSkill.mcp_auth_value || undefined,
			});
		} else if (skill_type === 'http') {
			config_json = JSON.stringify({ url: customSkill.http_url, method: customSkill.http_method });
		} else if (skill_type === 'function') {
			config_json = JSON.stringify({ code: customSkill.fn_code });
		} else if (skill_type === 'database') {
			config_json = JSON.stringify({ db_id: customSkill.db_id });
		}

		form.selectedSkills = [...form.selectedSkills, {
			name: name.trim(),
			version: '1.0',
			description: description.trim(),
			skill_type,
			config_json,
		}];
		customSkill = { ...customSkill, name: '', description: '', mcp_url: '', http_url: '', fn_code: '', db_id: '' };
	}

	// ── AI skill suggestion ───────────────────────────────────────────────────
	let isAnalyzing = $state(false);
	let suggestedSkills: LocalSkill[] = $state([]);

	async function analyzeJobDescription() {
		if (!form.jobDescription.trim()) return;
		isAnalyzing = true;
		suggestedSkills = [];
		await new Promise(r => setTimeout(r, 400));
		// Suggest company skills not yet selected (keyword matching)
		const text = form.jobDescription.toLowerCase();
		suggestedSkills = companySkills
			.filter(cs => !isCompanySkillSelected(cs.id) && (
				text.includes(cs.name.toLowerCase().split(' ')[0]) ||
				(cs.description && text.split(' ').some(w => w.length > 3 && cs.description!.toLowerCase().includes(w)))
			))
			.slice(0, 5)
			.map(cs => ({ name: cs.name, version: '', description: cs.description ?? '', _csId: cs.id } as any));
		isAnalyzing = false;
	}

	function acceptSuggestion(skill: LocalSkill) {
		const csId = (skill as any)._csId as string | undefined;
		if (csId) {
			if (!form.selectedCompanySkillIds.includes(csId)) {
				form.selectedCompanySkillIds = [...form.selectedCompanySkillIds, csId];
			}
		} else {
			form.selectedSkills = [...form.selectedSkills, { ...skill }];
		}
		suggestedSkills = suggestedSkills.filter(s => s.name !== skill.name);
	}

	function dismissSuggestion(skillName: string) {
		suggestedSkills = suggestedSkills.filter(s => s.name !== skillName);
	}

	// ── Policy helpers ────────────────────────────────────────────────────────
	function toggleAgentPolicy(policyId: string) {
		if (form.selectedAgentPolicyIds.includes(policyId)) {
			form.selectedAgentPolicyIds = form.selectedAgentPolicyIds.filter(id => id !== policyId);
		} else {
			form.selectedAgentPolicyIds = [...form.selectedAgentPolicyIds, policyId];
		}
	}

	// ── Change Request dialog ─────────────────────────────────────────────────
	let crTarget: PersonnelItem | null = $state(null);
	let showCrDialog = $state(false);
	let crForm = $state({ change_type: 'agent_config' as 'agent_config' | 'skill' | 'policy', title: '', proposed_json: '' });
	let crSaving = $state(false);

	function openCrDialog(agent: PersonnelItem) {
		crTarget = agent;
		const cfg = agent.agent_config;
		crForm = {
			change_type: 'agent_config',
			title: `${agent.name} - Yapılandırma Değişikliği`,
			proposed_json: JSON.stringify({ model: cfg?.model, status: cfg?.status, responsible_id: cfg?.responsible_id }, null, 2),
		};
		showCrDialog = true;
	}

	function setCrType(t: typeof crForm.change_type) {
		crForm.change_type = t;
		if (!crTarget) return;
		const cfg = crTarget.agent_config;
		if (t === 'agent_config') {
			crForm.proposed_json = JSON.stringify({ model: cfg?.model, status: cfg?.status, responsible_id: cfg?.responsible_id }, null, 2);
		} else if (t === 'skill') {
			crForm.proposed_json = JSON.stringify({ name: '', description: '' }, null, 2);
		} else {
			crForm.proposed_json = JSON.stringify({ policy_name: '', content: '' }, null, 2);
		}
	}

	async function submitCr() {
		if (!crTarget || !crForm.title) return;
		crSaving = true;
		try {
			let proposed: Record<string, unknown>;
			try { proposed = JSON.parse(crForm.proposed_json); } catch { proposed = { raw: crForm.proposed_json }; }
			await crApi.create({
				personnel_id: crTarget.id,
				change_type: crForm.change_type,
				title: crForm.title,
				proposed,
			}, companyStore.active?.id ?? '');
			showCrDialog = false;
			crTarget = null;
		} catch (e) { alert((e as Error).message); }
		finally { crSaving = false; }
	}

	async function submitAgentCr() {
		if (!editingId || !form.name || !form.title) return;
		crSaving = true;
		try {
			await crApi.create({
				personnel_id: editingId,
				change_type: 'agent_config',
				title: `${form.name} - Yapılandırma Güncellemesi`,
				proposed: {
					name: form.name,
					slug: form.slug,
					title: form.title,
					role: form.jobDescription,
					department_id: form.department_id || null,
					model: form.model,
					status: form.status,
					responsible_id: form.responsible_id || null,
					skills: form.selectedSkills,
					company_skill_ids: form.selectedCompanySkillIds,
					policy_ids: form.selectedAgentPolicyIds,
				},
			}, companyStore.active?.id ?? '');
			closePanel();
		} catch (e) { alert((e as Error).message); }
		finally { crSaving = false; }
	}
</script>

<svelte:head>
	<title>Ajanlar • fab.engineering</title>
</svelte:head>

<!-- ── Page ──────────────────────────────────────────────────────────────── -->
<div class="space-y-6">

	<YapiTabs />

	<!-- Header -->
	<div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
		<div>
			<h1 class="font-display text-3xl tracking-tight">{t('agent_title')}</h1>
			<p class="text-muted-foreground mt-1">{t('agent_subtitle')}</p>
		</div>
		<Button onclick={openCreate} class="w-full sm:w-auto">
			<Plus class="h-4 w-4" />
			{t('agent_new')}
		</Button>
	</div>

	<!-- Stats -->
	<div class="grid grid-cols-3 gap-3">
		<div class="rounded-xl border bg-card px-4 py-3">
			<div class="text-xs text-muted-foreground">{t('agent_stat_total')}</div>
			<div class="text-2xl font-semibold tracking-tight mt-0.5">{agents.length}</div>
		</div>
		<div class="rounded-xl border bg-card px-4 py-3">
			<div class="text-xs text-muted-foreground">{t('agent_stat_active')}</div>
			<div class="text-2xl font-semibold tracking-tight mt-0.5 text-emerald-600">{totalActive}</div>
		</div>
		<div class="rounded-xl border bg-card px-4 py-3">
			<div class="text-xs text-muted-foreground">{t('agent_stat_draft')}</div>
			<div class="text-2xl font-semibold tracking-tight mt-0.5 text-amber-500">{totalDraft}</div>
		</div>
	</div>

	<!-- Loading / Error / Table -->
	{#if loading}
		<div class="flex items-center justify-center py-20 text-muted-foreground gap-2">
			<Loader class="w-5 h-5 animate-spin" />
			<span class="text-sm">{t('loading')}</span>
		</div>
	{:else if error}
		<div class="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
			{error}
		</div>
	{:else if agents.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 text-center gap-3">
			<div class="w-12 h-12 rounded-xl bg-violet-100 flex items-center justify-center">
				<Bot class="w-6 h-6 text-violet-600" />
			</div>
			<div>
				<p class="font-medium">{t('agent_empty')}</p>
				<p class="text-sm text-muted-foreground mt-1">{t('agent_empty_subtitle')}</p>
			</div>
			<Button onclick={openCreate} size="sm" class="mt-2">
				<Plus class="h-4 w-4" /> {t('agent_new')}
			</Button>
		</div>
	{:else}
		<div class="rounded-xl border bg-card overflow-hidden">
			<Table>
				<thead>
					<tr class="border-b bg-muted/50 text-left text-sm font-medium text-muted-foreground">
						<th class="h-12 px-4">{t('agent_col_agent')}</th>
						<th class="h-12 px-4 hidden md:table-cell">{t('agent_col_model')}</th>
						<th class="h-12 px-4 hidden lg:table-cell">{t('agent_col_responsible')}</th>
						<th class="h-12 px-4 hidden lg:table-cell">{t('agent_col_dept')}</th>
						<th class="h-12 px-4">{t('agent_col_status')}</th>
						<th class="h-12 w-[120px] px-4 text-right">{t('agent_col_actions')}</th>
					</tr>
				</thead>
				<tbody class="divide-y">
					{#each agents as agent (agent.id)}
						<tr class="hover:bg-muted/30 transition-colors">
							<td class="px-4 py-3">
								<div class="flex items-center gap-3">
									<div class="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
										<Bot class="w-4 h-4 text-violet-600" />
									</div>
									<div>
										<div class="font-medium text-sm">{agent.name}</div>
										<div class="text-xs text-muted-foreground">{agent.title ?? agent.role ?? ''}</div>
									</div>
								</div>
							</td>
							<td class="px-4 py-3 hidden md:table-cell">
								<span class="text-xs font-mono bg-violet-50 text-violet-700 border border-violet-200 rounded-md px-2 py-0.5">
									{agent.agent_config?.model ?? '—'}
								</span>
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell">
								{agent.agent_config?.responsible_name ?? '—'}
							</td>
							<td class="px-4 py-3 text-sm text-muted-foreground hidden lg:table-cell">
								{agent.department_name ?? '—'}
							</td>
							<td class="px-4 py-3">
								<Badge variant={STATUS_BADGE[agent.agent_config?.status ?? 'draft']}>{(() => { const s = agent.agent_config?.status ?? 'draft'; return s === 'active' ? t('status_active') : s === 'draft' ? t('status_draft') : t('status_inactive'); })()}</Badge>
							</td>
							<td class="px-4 py-3">
								<div class="flex justify-end gap-1">
									<Button variant="ghost" size="icon" onclick={() => openCrDialog(agent)} aria-label={t('agent_cr_btn')} title={t('agent_cr_tooltip')} class="text-amber-600 hover:text-amber-700 hover:bg-amber-50">
										<GitPullRequest class="h-4 w-4" />
									</Button>
									<Button variant="ghost" size="icon" onclick={() => openEdit(agent)} aria-label={t('edit')}>
										<Pencil class="h-4 w-4" />
									</Button>
									<Button variant="ghost" size="icon" onclick={() => requestDelete(agent)} aria-label={t('delete')}
										class="text-destructive hover:text-destructive hover:bg-destructive/10">
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

<!-- ── Form Panel ────────────────────────────────────────────────────────── -->
{#if showPanel}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 bg-black/30 z-30 lg:hidden" onclick={closePanel} aria-hidden="true"></div>

	<aside class="agent-panel" aria-label={t('agent_title')}>

		<!-- Panel Header -->
		<div class="panel-hdr">
			<div>
				<h2 class="font-display text-lg tracking-tight">
					{editingId ? t('agent_edit_title') : t('agent_create_title')}
				</h2>
				<p class="text-xs text-muted-foreground mt-0.5">
					{editingId ? t('agent_edit_subtitle') : t('agent_create_subtitle')}
				</p>
			</div>
			<Button variant="ghost" size="icon" onclick={closePanel} aria-label={t('close')}>
				<X class="w-4 h-4" />
			</Button>
		</div>

		<!-- Scrollable body -->
		<div class="panel-body">

			<!-- ① Temel Bilgiler -->
			<section class="form-section">
				<div class="section-title">{t('agent_basic_info')}</div>
				<div class="space-y-3">
					<div class="field">
						<label for="ag-name">{t('agent_name_label')}</label>
						<Input id="ag-name" bind:value={form.name} placeholder="CodeGuard" autocomplete="off" />
					</div>
					<div class="field">
						<label for="ag-slug">{t('agent_slug_label')}</label>
						<Input id="ag-slug" bind:value={form.slug} placeholder="codeguard" class="font-mono text-xs" autocomplete="off" />
					</div>
					<div class="field">
						<label for="ag-title">{t('agent_title_label')}</label>
						<Input id="ag-title" bind:value={form.title} placeholder="Code Review Agent" autocomplete="off" />
					</div>
					<div class="field">
						<label for="ag-status">{t('agent_status_label')}</label>
						<select id="ag-status" class="select-input" bind:value={form.status}>
							<option value="draft">{t('status_draft')}</option>
							<option value="active">{t('status_active')}</option>
							<option value="inactive">{t('status_inactive')}</option>
						</select>
					</div>
				</div>
			</section>

			<!-- ② Model & Bağlantılar -->
			<section class="form-section">
				<div class="section-title">{t('agent_model_section')}</div>
				<div class="space-y-3">
					<div class="grid grid-cols-2 gap-3">
						<div class="field">
							<label for="ag-model">{t('agent_model_label')}</label>
							{#if modelsLoading}
								<div class="select-input text-muted-foreground text-sm flex items-center gap-x-2">
									<span class="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
									Modeller yükleniyor...
								</div>
							{:else if availableModels.length === 0}
								<div class="select-input text-muted-foreground text-sm">
									Aktif AI sağlayıcısı yok — Ayarlar &gt; AI Sağlayıcılar
								</div>
							{:else}
								<select id="ag-model" class="select-input" bind:value={form.model}>
									{#each availableModels as m}
										<option value={m.id}>{modelLabel(m)} · {modelTierHint(m)}</option>
									{/each}
								</select>
								{#if form.model}
									{@const selected = availableModels.find(m => m.id === form.model)}
									{#if selected}
										<p class="text-xs mt-1 {TIER_COLOR[selected.tier]}">
											{#if selected.tier === 'premium'}⚠ Pahalı model — yüksek token kullanımında maliyet hızlı artar.
											{:else if selected.tier === 'high'}Yüksek maliyetli model.
											{:else if selected.tier === 'medium'}Orta maliyetli model.
											{:else}Düşük maliyetli model.{/if}
											{#if selected.input_per_m != null}
												Giriş: ${selected.input_per_m}/1M · Çıkış: ${selected.output_per_m}/1M token.
											{/if}
										</p>
									{/if}
								{/if}
							{/if}
						</div>
					</div>
					<div class="field">
						<label for="ag-human">{t('agent_responsible_label')}</label>
						<select id="ag-human" class="select-input" bind:value={form.responsible_id}>
							<option value="">{t('select_placeholder')}</option>
							{#each humanPersonnel as p}
								<option value={p.id}>{p.name}</option>
							{/each}
						</select>
					</div>
					<div class="field">
						<label for="ag-dept">{t('agent_dept_label')}</label>
						<select id="ag-dept" class="select-input" bind:value={form.department_id}>
							<option value="">{t('select_placeholder')}</option>
							{#each depts as d}
								<option value={d.id}>{d.name}</option>
							{/each}
						</select>
						{#if form.department_id}
							<p class="text-xs text-muted-foreground mt-1">
								{t('agent_dept_policies_hint')}
							</p>
						{/if}
					</div>
				</div>
			</section>

			<!-- ③ İş Tanımı & Skill Önerisi -->
			<section class="form-section">
				<div class="section-title flex items-center justify-between">
					<span>{t('agent_job_section')}</span>
					<button
						class="suggest-btn"
						onclick={analyzeJobDescription}
						disabled={isAnalyzing || !form.jobDescription.trim()}
						type="button"
					>
						{#if isAnalyzing}
							<span class="spinner"></span>
							{t('agent_analyzing')}
						{:else}
							<Sparkles class="w-3.5 h-3.5" />
							{t('agent_skill_suggest_btn')}
						{/if}
					</button>
				</div>
				<textarea
					class="textarea-input"
					bind:value={form.jobDescription}
					placeholder="Bu ajanın ne yapacağını açıklayın... (örn: Kod kalitesini artırmak, PR incelemek ve güvenlik açıklarını tespit etmek)"
					rows="3"
				></textarea>

				{#if suggestedSkills.length > 0}
					<div class="suggestion-box">
						<div class="text-xs font-semibold text-violet-700 mb-2 flex items-center gap-1.5">
							<Sparkles class="w-3 h-3" />
							{t('agent_suggested_skills')}
						</div>
						<div class="flex flex-wrap gap-2">
							{#each suggestedSkills as skill}
								<div class="suggestion-chip">
									<span>{skill.name}</span>
									<button onclick={() => acceptSuggestion(skill)} type="button" aria-label={t('add')}>
										<Check class="w-3 h-3" />
									</button>
									<button onclick={() => dismissSuggestion(skill.name)} type="button" aria-label={t('close')}>
										<X class="w-3 h-3" />
									</button>
								</div>
							{/each}
						</div>
					</div>
				{/if}
			</section>

			<!-- ④ Yetenekler (CompanySkill) -->
			<section class="form-section">
				<div class="section-title">{t('agent_skills_section')}</div>

				{#if companySkills.length > 0}
					<div class="mb-3">
						<div class="text-xs text-muted-foreground mb-2">Şirket Yetenekleri — seçililer ajana bağlanır</div>
						<div class="flex flex-wrap gap-1.5">
							{#each companySkills as cs}
								{@const sel = isCompanySkillSelected(cs.id)}
								<button
									type="button"
									class="skill-chip"
									class:skill-chip-on={sel}
									onclick={() => toggleCompanySkill(cs.id)}
									title={cs.description ?? cs.name}
								>
									{#if sel}<Check class="w-3 h-3" />{/if}
									{cs.name}
								</button>
							{/each}
						</div>
					</div>
				{:else}
					<p class="text-xs text-muted-foreground mb-3">
						Henüz şirket yeteneği yok — <a href="/skills" class="underline">Yetenekler</a> bölümünden ekleyebilirsiniz.
					</p>
				{/if}

				<!-- Custom skill -->
				<div class="custom-skill-form">
					<div class="text-xs text-muted-foreground mb-2">{t('agent_custom_skill')}</div>

					<div class="flex gap-1.5 mb-3 flex-wrap">
						{#each SKILL_TYPES as st}
							<button
								type="button"
								class="type-chip"
								class:type-chip-on={customSkill.skill_type === st.value}
								onclick={() => (customSkill.skill_type = st.value)}
								title={st.hint}
							>
								{st.label}
							</button>
						{/each}
					</div>

					<div class="mb-2">
						<Input bind:value={customSkill.name} placeholder={t('agent_skill_name_ph')} class="text-xs h-8" />
					</div>
					<div class="mb-2">
						<Input bind:value={customSkill.description} placeholder={t('agent_skill_desc_ph')} class="text-xs h-8" />
					</div>

					{#if customSkill.skill_type === 'builtin'}
						<select class="select-input text-xs h-8 mb-2" bind:value={customSkill.builtin_fn}
								disabled={builtinToolsLoading}>
							{#if builtinToolsLoading}
								<option value="">Yükleniyor…</option>
							{:else}
								{#each builtinTools as f}
									<option value={f.value}>
										{f.icon} {i18n.locale === 'en' ? f.label_en : f.label_tr}
									</option>
								{/each}
							{/if}
						</select>
					{/if}

					{#if customSkill.skill_type === 'mcp'}
						<div class="space-y-2 mb-2">
							<Input bind:value={customSkill.mcp_url} placeholder="MCP Sunucu URL (https://...)" class="text-xs h-8 font-mono" />
							<div class="grid grid-cols-2 gap-2">
								<select class="select-input text-xs h-8" bind:value={customSkill.mcp_transport}>
									<option value="sse">SSE</option>
									<option value="http">HTTP</option>
									<option value="stdio">stdio</option>
								</select>
								<select class="select-input text-xs h-8" bind:value={customSkill.mcp_auth_type}>
									<option value="none">Auth yok</option>
									<option value="api_key">API Key</option>
									<option value="bearer">Bearer Token</option>
								</select>
							</div>
							{#if customSkill.mcp_auth_type !== 'none'}
								<Input bind:value={customSkill.mcp_auth_value} placeholder="API Key / Token değeri" class="text-xs h-8 font-mono" />
							{/if}
						</div>
					{/if}

					{#if customSkill.skill_type === 'http'}
						<div class="space-y-2 mb-2">
							<Input bind:value={customSkill.http_url} placeholder="Endpoint URL (https://...)" class="text-xs h-8 font-mono" />
							<select class="select-input text-xs h-8" bind:value={customSkill.http_method}>
								<option value="POST">POST</option>
								<option value="GET">GET</option>
								<option value="PUT">PUT</option>
							</select>
						</div>
					{/if}

					{#if customSkill.skill_type === 'function'}
						<textarea
							class="textarea-input text-xs font-mono mb-2"
							bind:value={customSkill.fn_code}
							placeholder="def run(args: dict) -> str:&#10;    # args içindeki parametrelere erişin&#10;    value = args.get('input', '')&#10;    return f'Sonuç: &#123;value&#125;'"
							rows="6"
						></textarea>
						<p class="text-xs text-muted-foreground mb-2">
							Fonksiyon <code>run(args: dict) → str</code> imzasına sahip olmalı. Güvenli ortamda çalışır (5 sn timeout).
						</p>
					{/if}

					{#if customSkill.skill_type === 'database'}
						<div class="space-y-1.5 mb-2">
							<select class="select-input text-xs h-8" bind:value={customSkill.db_id}>
								<option value="">Veritabanı seçin...</option>
								{#each databases as db}
									<option value={db.id}>{db.name} ({db.db_type}) {db.status === 'ok' ? '✓' : '⚠'}</option>
								{/each}
							</select>
							{#if databases.length === 0}
								<p class="text-xs text-muted-foreground">
									Henüz veritabanı eklenmemiş — <a href="/settings" class="underline">Ayarlar → Veritabanları</a>
								</p>
							{/if}
						</div>
					{/if}

					<Button size="sm" variant="outline" onclick={addCustomSkill} disabled={!customSkill.name.trim()} class="h-8 px-3 text-xs w-full">
						<Plus class="w-3 h-3" /> {t('add')}
					</Button>
				</div>

				{#if form.selectedSkills.length > 0}
					<div class="mt-3 space-y-2">
						<div class="text-xs text-muted-foreground">{t('agent_selected_skills')} ({form.selectedSkills.length}):</div>
						{#each form.selectedSkills as skill}
							{@const cfg = (() => { try { return skill.config_json ? JSON.parse(skill.config_json) : {}; } catch { return {}; } })()}
							{@const typeLabel = skill.skill_type === 'builtin' ? 'Dahili' : skill.skill_type === 'mcp' ? 'MCP' : skill.skill_type === 'http' ? 'HTTP' : skill.skill_type === 'function' ? 'Fonksiyon' : skill.skill_type === 'database' ? 'Veritabanı' : skill.skill_type ?? ''}
							<div class="selected-skill-row flex-col !items-start gap-1 py-2.5">
								<div class="flex items-center justify-between w-full">
									<div class="flex items-center gap-2 min-w-0 flex-wrap">
										<span class="text-sm font-medium truncate">{skill.name}</span>
										<span class="version-badge">v{skill.version}</span>
										{#if typeLabel}<span class="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-mono">{typeLabel}</span>{/if}
									</div>
									<button
										type="button"
										onclick={() => { form.selectedSkills = form.selectedSkills.filter(s => s.name !== skill.name); }}
										class="text-muted-foreground hover:text-destructive transition-colors flex-shrink-0 ml-2"
										aria-label={t('remove')}
									>
										<X class="w-3.5 h-3.5" />
									</button>
								</div>
								{#if skill.description}
									<p class="text-xs text-muted-foreground leading-relaxed">{skill.description}</p>
								{/if}
								{#if skill.skill_type === 'builtin' && cfg.function_name}
									<span class="text-[10px] font-mono text-violet-600 bg-violet-50 px-1.5 py-0.5 rounded">fn: {cfg.function_name}</span>
								{/if}
								{#if skill.skill_type === 'mcp' && cfg.url}
									<span class="text-[10px] font-mono text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded truncate max-w-full">{cfg.url}</span>
								{/if}
								{#if skill.skill_type === 'http' && cfg.url}
									<span class="text-[10px] font-mono text-green-600 bg-green-50 px-1.5 py-0.5 rounded truncate max-w-full">{cfg.method ?? 'GET'} {cfg.url}</span>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</section>

			<!-- ⑤ Politikalar -->
			<section class="form-section">
				<div class="section-title">{t('agent_policies_section')}</div>

				{#if companyPolicies.length === 0}
					<p class="text-xs text-muted-foreground italic">
						Henüz politika oluşturulmamış.
						<a href="/policies" class="underline text-primary">Politikalar</a> sayfasından ekleyin.
					</p>
				{:else}
					{@const companyLevelPolicies = companyPolicies.filter(p => p.scope === 'company')}
					{@const deptLevelPolicies = companyPolicies.filter(p => p.scope === 'department' && inheritedPolicyIds.includes(p.id))}
					{@const agentLevelPolicies = companyPolicies.filter(p => p.scope === 'agent')}
					<!-- Şirket politikaları — her zaman kilitli -->
					{#if companyLevelPolicies.length > 0}
						<div class="mb-3">
							<div class="text-xs font-medium text-muted-foreground mb-1.5">
								Şirket Politikaları <span class="text-[10px] bg-muted px-1.5 py-0.5 rounded ml-1">her zaman aktif</span>
							</div>
							<div class="space-y-1">
								{#each companyLevelPolicies as policy}
									<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/30 border border-border/50 opacity-70 cursor-not-allowed">
										<div class="w-4 h-4 rounded border-2 border-emerald-400 bg-emerald-500 flex items-center justify-center flex-shrink-0">
											<Check class="w-2.5 h-2.5 text-white" />
										</div>
										<span class="text-xs flex-1 truncate text-muted-foreground">{policy.name}</span>
									</div>
								{/each}
							</div>
						</div>
					{/if}

					<!-- Bölüm politikaları — kilitli, bölümden kalıtılmış -->
					{#if deptLevelPolicies.length > 0}
						<div class="mb-3">
							<div class="text-xs font-medium text-muted-foreground mb-1.5 flex items-center gap-1">
								<span>Bölüm Politikaları</span>
								<span class="text-[10px] bg-muted px-1.5 py-0.5 rounded">{selectedDeptName}</span>
							</div>
							<div class="space-y-1">
								{#each deptLevelPolicies as policy}
									<div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/40 border border-border/50 opacity-75 cursor-not-allowed">
										<div class="w-4 h-4 rounded border-2 border-emerald-400 bg-emerald-500 flex items-center justify-center flex-shrink-0">
											<Check class="w-2.5 h-2.5 text-white" />
										</div>
										<span class="text-xs flex-1 truncate text-muted-foreground">{policy.name}</span>
										<span class="text-[10px] text-muted-foreground/60 flex-shrink-0">bölümden</span>
									</div>
								{/each}
							</div>
						</div>
					{:else if form.department_id}
						<p class="text-xs text-muted-foreground mb-3 italic">Bu bölüme atanmış bölüm politikası yok.</p>
					{/if}

					<!-- Ajan politikaları — toggle edilebilir -->
					{#if agentLevelPolicies.length > 0}
						<div>
							<div class="text-xs font-medium text-muted-foreground mb-1.5">Ajana Özel</div>
							<div class="space-y-1 max-h-56 overflow-y-auto pr-1">
								{#each agentLevelPolicies as policy}
									{@const selected = form.selectedAgentPolicyIds.includes(policy.id)}
									<button
										type="button"
										class="w-full flex items-center gap-2 px-3 py-2 rounded-lg border transition-colors text-left
											{selected
												? 'bg-violet-50 border-violet-300'
												: 'bg-background border-border hover:bg-muted/50'}"
										onclick={() => toggleAgentPolicy(policy.id)}
									>
										<div class="w-4 h-4 rounded border-2 flex items-center justify-center flex-shrink-0 transition-colors
											{selected ? 'bg-violet-500 border-violet-500' : 'border-muted-foreground/40'}">
											{#if selected}<Check class="w-2.5 h-2.5 text-white" />{/if}
										</div>
										<span class="text-xs flex-1 truncate {selected ? 'text-violet-900 font-medium' : 'text-foreground'}">{policy.name}</span>
									</button>
								{/each}
							</div>
						</div>
					{:else}
						<p class="text-xs text-muted-foreground italic">
							Ajan kapsamında politika oluşturulmamış.
							<a href="/policies" class="underline text-primary">Politikalar</a> sayfasından "Ajan" kapsamında ekleyin.
						</p>
					{/if}

					{#if !form.department_id && companyLevelPolicies.length === 0 && agentLevelPolicies.length === 0}
						<p class="text-xs text-muted-foreground mt-2 italic">Bölüm seçince bölüm politikaları otomatik eklenir.</p>
					{/if}
				{/if}
			</section>

		</div>

		<!-- Panel Footer -->
		<div class="panel-footer">
			<Button variant="outline" onclick={closePanel} class="flex-1 sm:flex-none">{t('cancel')}</Button>
			{#if editingId}
				<Button
					onclick={submitAgentCr}
					disabled={!form.name || !form.title || crSaving}
					class="flex-1 sm:flex-none bg-amber-600 hover:bg-amber-700 text-white"
				>
					{crSaving ? t('agent_cr_submitting') : t('agent_cr_submit')}
				</Button>
			{:else}
				<Button onclick={saveAgent} disabled={!form.name || !form.title || saving} class="flex-1 sm:flex-none">
					{saving ? t('saving') : t('create')}
				</Button>
			{/if}
		</div>
	</aside>
{/if}

<!-- ── Delete Dialog ─────────────────────────────────────────────────────── -->
{#if showDeleteDialog}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 animate-backdrop" onclick={cancelDelete}>
		<div class="bg-background w-full max-w-sm rounded-xl border p-6 shadow-lg mx-4 animate-dialog" onclick={(e) => e.stopPropagation()}>
			<h2 class="font-display text-xl tracking-tight">{t('agent_delete_title')}</h2>
			<p class="text-sm text-muted-foreground mt-1">
				<strong class="text-foreground">{deleteTarget?.name}</strong> {t('agent_delete_confirm')}
			</p>
			<div class="flex gap-3 justify-end mt-5">
				<Button variant="outline" onclick={cancelDelete}>{t('cancel')}</Button>
				<Button variant="destructive" onclick={confirmDelete} disabled={deleting}>
					{deleting ? t('deleting') : t('delete')}
				</Button>
			</div>
		</div>
	</div>
{/if}

<!-- ── Change Request Dialog ─────────────────────────────────────────────── -->
{#if showCrDialog}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 animate-backdrop" onclick={() => (showCrDialog = false)}>
		<div class="bg-background w-full max-w-lg rounded-xl border p-6 shadow-lg mx-4 animate-dialog space-y-4" onclick={(e) => e.stopPropagation()} role="dialog">
			<div class="flex items-start justify-between gap-2">
				<div>
					<h2 class="font-display text-xl tracking-tight">{t('agent_cr_title')}</h2>
					<p class="text-sm text-muted-foreground mt-0.5">{crTarget?.name}</p>
				</div>
				<button onclick={() => (showCrDialog = false)} class="text-muted-foreground hover:text-foreground mt-0.5">
					<X class="w-4 h-4" />
				</button>
			</div>

			<div class="space-y-1">
				<label class="text-xs font-medium text-muted-foreground">{t('agent_cr_type_label')}</label>
				<div class="flex gap-2">
					{#each [{ v: 'agent_config', l: t('agent_cr_type_config') }, { v: 'skill', l: t('agent_cr_type_skill') }, { v: 'policy', l: t('agent_cr_type_policy') }] as crType}
						<button
							onclick={() => setCrType(crType.v as typeof crForm.change_type)}
							class={['flex-1 py-1.5 rounded-lg text-xs font-medium border transition-colors', crForm.change_type === crType.v ? 'bg-amber-50 border-amber-300 text-amber-800' : 'border-input text-muted-foreground hover:text-foreground'].join(' ')}
						>
							{crType.l}
						</button>
					{/each}
				</div>
			</div>

			<div class="space-y-1">
				<label class="text-xs font-medium text-muted-foreground">{t('agent_cr_title_label')} *</label>
				<input bind:value={crForm.title} class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring" placeholder="Değişikliği kısaca açıklayın..." />
			</div>

			<div class="space-y-1">
				<label class="text-xs font-medium text-muted-foreground">{t('agent_cr_proposed_label')}</label>
				<textarea
					bind:value={crForm.proposed_json}
					rows={6}
					class="w-full px-3 py-2 text-xs font-mono rounded-lg border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-none"
				></textarea>
			</div>

			<div class="flex gap-3 justify-end pt-1">
				<Button variant="outline" onclick={() => (showCrDialog = false)}>{t('cancel')}</Button>
				<Button onclick={submitCr} disabled={crSaving || !crForm.title} class="bg-amber-600 hover:bg-amber-700 text-white">
					{crSaving ? t('agent_cr_submitting') : t('agent_cr_submit')}
				</Button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* ── Agent Panel ── */
	.agent-panel {
		position: fixed;
		top: 0; right: 0; bottom: 0;
		width: 600px;
		max-width: 100vw;
		background: hsl(var(--card));
		border-left: 1px solid hsl(var(--border));
		box-shadow: -8px 0 32px rgba(0,0,0,0.1);
		z-index: 40;
		display: flex;
		flex-direction: column;
		animation: panelIn 0.2s cubic-bezier(0.32,0.72,0,1);
	}
	@keyframes panelIn {
		from { transform: translateX(100%); opacity: 0; }
		to   { transform: translateX(0);    opacity: 1; }
	}

	.panel-hdr {
		display: flex; align-items: flex-start;
		justify-content: space-between;
		padding: 1.25rem 1.5rem;
		border-bottom: 1px solid hsl(var(--border));
		flex-shrink: 0;
	}

	.panel-body {
		flex: 1; overflow-y: auto;
		padding: 1.25rem 1.5rem;
		display: flex; flex-direction: column; gap: 1.5rem;
	}

	.panel-footer {
		display: flex; gap: 0.75rem;
		justify-content: flex-end;
		padding: 1rem 1.5rem;
		border-top: 1px solid hsl(var(--border));
		flex-shrink: 0;
		background: hsl(var(--card));
	}

	/* ── Form sections ── */
	.form-section {
		display: flex; flex-direction: column; gap: 0.75rem;
		padding-bottom: 1.5rem;
		border-bottom: 1px solid hsl(var(--border) / 0.6);
	}
	.form-section:last-child { border-bottom: none; padding-bottom: 0; }

	.section-title {
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: hsl(var(--muted-foreground));
		display: flex; align-items: center;
	}

	.field { display: flex; flex-direction: column; gap: 0.375rem; }
	.field label {
		font-size: 0.8125rem;
		font-weight: 500;
		color: hsl(var(--foreground));
	}

	.select-input {
		height: 2.25rem;
		width: 100%;
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--input));
		background: hsl(var(--background));
		padding: 0 0.75rem;
		font-size: 0.875rem;
		color: hsl(var(--foreground));
		transition: border-color 0.15s;
		outline: none;
	}
	.select-input:focus { box-shadow: 0 0 0 1px hsl(var(--ring)); }

	.textarea-input {
		width: 100%;
		border-radius: 0.375rem;
		border: 1px solid hsl(var(--input));
		background: hsl(var(--background));
		padding: 0.5rem 0.75rem;
		font-size: 0.8125rem;
		color: hsl(var(--foreground));
		resize: vertical;
		min-height: 72px;
		outline: none;
		font-family: inherit;
		line-height: 1.5;
		transition: border-color 0.15s;
	}
	.textarea-input::placeholder { color: hsl(var(--muted-foreground)); }
	.textarea-input:focus { box-shadow: 0 0 0 1px hsl(var(--ring)); }

	/* ── Skill Öner button ── */
	.suggest-btn {
		display: inline-flex; align-items: center; gap: 0.375rem;
		font-size: 0.6875rem; font-weight: 600;
		color: #7c3aed;
		background: #f5f3ff;
		border: 1px solid #c4b5fd;
		border-radius: 0.5rem;
		padding: 0.25rem 0.625rem;
		transition: all 0.15s;
		white-space: nowrap;
		cursor: pointer;
	}
	.suggest-btn:hover:not(:disabled) { background: #ede9fe; border-color: #7c3aed; }
	.suggest-btn:disabled { opacity: 0.5; cursor: not-allowed; }

	.spinner {
		width: 10px; height: 10px;
		border: 2px solid #c4b5fd;
		border-top-color: #7c3aed;
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
		flex-shrink: 0;
	}
	@keyframes spin { to { transform: rotate(360deg); } }

	/* ── Suggestions ── */
	.suggestion-box {
		background: #f5f3ff;
		border: 1px solid #c4b5fd;
		border-radius: 0.75rem;
		padding: 0.75rem;
		margin-top: 0.5rem;
	}
	.suggestion-chip {
		display: inline-flex; align-items: center; gap: 0.25rem;
		background: white;
		border: 1.5px solid #a78bfa;
		border-radius: 999px;
		padding: 0.2rem 0.5rem 0.2rem 0.625rem;
		font-size: 0.6875rem; font-weight: 600; color: #5b21b6;
	}
	.suggestion-chip button {
		display: flex; align-items: center; justify-content: center;
		width: 14px; height: 14px; border-radius: 50%;
		background: none; border: none; cursor: pointer;
		color: #7c3aed; transition: color 0.15s;
	}
	.suggestion-chip button:last-child { color: #94a3b8; }
	.suggestion-chip button:hover { color: #4c1d95; }

	/* ── Skill chips ── */
	.skill-chip {
		display: inline-flex; align-items: center; gap: 0.25rem;
		padding: 0.2rem 0.625rem;
		border-radius: 999px;
		border: 1px solid hsl(var(--border));
		background: hsl(var(--muted) / 0.4);
		font-size: 0.6875rem; font-weight: 500;
		color: hsl(var(--foreground));
		cursor: pointer; transition: all 0.12s;
		white-space: nowrap;
	}
	.skill-chip:hover { border-color: #a78bfa; background: #f5f3ff; color: #6d28d9; }
	.skill-chip-on {
		background: #ede9fe; border-color: #7c3aed;
		color: #5b21b6; font-weight: 600;
	}
	.chip-version { font-size: 0.5625rem; font-family: monospace; color: hsl(var(--muted-foreground)); margin-left: 1px; }

	/* ── Custom skill form ── */
	.custom-skill-form {
		background: hsl(var(--muted) / 0.3);
		border: 1px dashed hsl(var(--border));
		border-radius: 0.75rem;
		padding: 0.75rem;
	}

	.type-chip {
		font-size: 0.6875rem; font-weight: 600;
		padding: 0.2rem 0.625rem;
		border-radius: 999px;
		border: 1px solid hsl(var(--border));
		background: hsl(var(--background));
		color: hsl(var(--muted-foreground));
		cursor: pointer; transition: all 0.12s;
	}
	.type-chip:hover { border-color: #a78bfa; color: #6d28d9; }
	.type-chip-on {
		background: #ede9fe; border-color: #7c3aed;
		color: #5b21b6;
	}

	/* ── Selected skill row ── */
	.selected-skill-row {
		display: flex; align-items: center;
		justify-content: space-between;
		background: hsl(var(--muted) / 0.4);
		border: 1px solid hsl(var(--border) / 0.6);
		border-radius: 0.625rem;
		padding: 0.4rem 0.625rem;
		gap: 0.5rem;
	}
	.version-badge {
		font-size: 0.5625rem; font-family: monospace;
		background: hsl(var(--muted));
		border-radius: 0.25rem;
		padding: 1px 4px;
		color: hsl(var(--muted-foreground));
		flex-shrink: 0;
	}

	/* ── Policy toggles ── */
	.policy-toggle {
		display: flex; align-items: center; gap: 0.625rem;
		width: 100%;
		background: hsl(var(--muted) / 0.3);
		border: 1px solid hsl(var(--border) / 0.5);
		border-radius: 0.625rem;
		padding: 0.5rem 0.75rem;
		text-align: left; cursor: pointer;
		transition: all 0.12s;
	}
	.policy-toggle:hover { background: hsl(var(--muted) / 0.6); }
	.policy-toggle-on {
		background: #f0fdf4;
		border-color: #86efac;
	}

	.policy-check {
		width: 16px; height: 16px; min-width: 16px;
		border-radius: 0.25rem;
		border: 1.5px solid hsl(var(--border));
		background: white;
		display: flex; align-items: center; justify-content: center;
		transition: all 0.12s;
	}
	.policy-check-on {
		background: #22c55e;
		border-color: #22c55e;
	}

	/* ── Dialog animations ── */
	.animate-backdrop { animation: fadeIn 0.15s ease; }
	.animate-dialog   { animation: scaleIn 0.2s cubic-bezier(0.32,0.72,0,1); }
	@keyframes fadeIn  { from { opacity: 0; } to { opacity: 1; } }
	@keyframes scaleIn { from { transform: scale(0.95); opacity: 0; } to { transform: scale(1); opacity: 1; } }
</style>
