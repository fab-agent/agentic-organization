<script lang="ts">
	import { onMount } from 'svelte';
	import { providers as providerApi, type ProviderStatus } from '$lib/api/providers.js';
	import { git as gitApi, type GitConfig, type SyncLog } from '$lib/api/git.js';
	import { api } from '$lib/api/client.js';
	import { telegram as telegramApi, type TelegramConfigResponse } from '$lib/api/telegram.js';
	import { companyStore } from '$lib/stores/company.svelte';
	import Button from '$lib/components/ui/button.svelte';
	import {
		Settings,
		Cpu,
		Globe,
		Server,
		GitBranch,
		CheckCircle2,
		XCircle,
		Circle,
		Eye,
		EyeOff,
		RefreshCw,
		Trash2,
		Link,
		Unlink,
		ArrowDown,
		ArrowUp,
		AlertTriangle,
		Loader2,
		Clock,
		User,
		Database,
		CloudUpload,
		History,
		ShieldCheck,
		Share2,
		MessageSquare,
		Table2,
		Code2,
		Plus,
		X,
		RefreshCcw,
		AlertCircle
	} from '@lucide/svelte';
	import { t } from '$lib/i18n/index.svelte';
	import { goto } from '$app/navigation';
	import { onboardingApi } from '$lib/api/onboarding';
	import { Sparkles } from '@lucide/svelte';

	// ── Tabs ─────────────────────────────────────────────────────────────────
	let tab = $state<'providers' | 'git' | 'audit' | 'backup' | 'social' | 'databases'>('providers');

	// ── AI Onboarding state ───────────────────────────────────────────────────
	let aiOnboarded = $state<boolean | null>(null);
	let onboardingLoading = $state(false);

	// ── Provider state ────────────────────────────────────────────────────────
	const LOCAL_PROVIDER_SLUGS = new Set(['ollama', 'lmstudio']);
	const LOCAL_PROVIDER_DEFAULTS: Record<string, string> = {
		ollama: 'http://localhost:11434/v1',
		lmstudio: 'http://localhost:1234/v1',
	};

	type ProviderCard = ProviderStatus & {
		keyInput: string;
		urlInput: string;
		showKey: boolean;
		editMode: boolean;   // expand key input for already-configured
		connectMode: boolean; // expand connect form for unconfigured
		saving: boolean;
		testing: boolean;
		deleting: boolean;
		error: string;
	};

	let providerCards = $state<ProviderCard[]>([]);
	let providerLoading = $state(true);

	const configuredProviders = $derived(providerCards.filter((c) => c.has_key));
	const unconfiguredProviders = $derived(providerCards.filter((c) => !c.has_key));

	async function loadProviders() {
		providerLoading = true;
		try {
			const list = await providerApi.status();
			providerCards = list.map((p) => ({
				...p,
				keyInput: '',
				urlInput: LOCAL_PROVIDER_DEFAULTS[p.provider] ?? '',
				showKey: false,
				editMode: false,
				connectMode: false,
				saving: false,
				testing: false,
				deleting: false,
				error: ''
			}));
		} finally {
			providerLoading = false;
		}
	}

	async function connectProvider(card: ProviderCard) {
		const isLocal = LOCAL_PROVIDER_SLUGS.has(card.provider);
		if (!isLocal && !card.keyInput.trim()) return;
		card.saving = true;
		card.error = '';
		try {
			const key = isLocal ? 'local' : card.keyInput.trim();
			const base_url = isLocal ? (card.urlInput.trim() || LOCAL_PROVIDER_DEFAULTS[card.provider]) : undefined;
			const updated = await providerApi.setKey(card.provider, key, base_url);
			Object.assign(card, updated, {
				keyInput: '', showKey: false, connectMode: false, editMode: false, saving: false,
				urlInput: LOCAL_PROVIDER_DEFAULTS[card.provider] ?? '',
				error: updated.status === 'invalid'
					? (isLocal ? t('settings_provider_local_unreachable') : t('settings_provider_invalid_err'))
					: ''
			});
		} catch {
			card.error = t('settings_provider_save_err');
		} finally {
			card.saving = false;
		}
	}

	async function saveKey(card: ProviderCard) {
		if (!card.keyInput.trim()) return;
		card.saving = true;
		card.error = '';
		try {
			const isLocal = LOCAL_PROVIDER_SLUGS.has(card.provider);
			const key = isLocal ? 'local' : card.keyInput.trim();
			const base_url = isLocal ? (card.urlInput.trim() || LOCAL_PROVIDER_DEFAULTS[card.provider]) : undefined;
			const updated = await providerApi.setKey(card.provider, key, base_url);
			Object.assign(card, updated, {
				keyInput: '', showKey: false, editMode: updated.status !== 'active', saving: false,
				error: updated.status === 'invalid'
					? (isLocal ? t('settings_provider_local_unreachable') : t('settings_provider_invalid_err'))
					: ''
			});
		} catch {
			card.saving = false;
			card.error = t('settings_provider_save_err');
		}
	}

	async function testKey(card: ProviderCard) {
		card.testing = true;
		card.error = '';
		try {
			const updated = await providerApi.test(card.provider);
			Object.assign(card, updated, {
				testing: false,
				editMode: updated.status !== 'active',
				error: updated.status === 'invalid' ? t('settings_provider_invalid_err') : ''
			});
		} catch {
			card.testing = false;
			card.error = t('settings_provider_test_err');
		}
	}

	async function deleteKey(card: ProviderCard) {
		card.deleting = true;
		try {
			await providerApi.deleteKey(card.provider);
			card.status = 'unconfigured';
			card.has_key = false;
			card.models = [];
			card.last_tested = null;
			card.editMode = false;
			card.connectMode = false;
			card.keyInput = '';
			card.error = '';
		} finally {
			card.deleting = false;
		}
	}

	// ── Git state ─────────────────────────────────────────────────────────────
	let gitConfig = $state<GitConfig | null>(null);
	let gitLogs = $state<SyncLog[]>([]);
	let gitLoading = $state(true);
	let gitSyncing = $state<'pull' | 'push' | null>(null);
	let gitConnecting = $state(false);
	let gitDisconnecting = $state(false);
	let gitError = $state('');

	// connect form
	let gitForm = $state({
		provider: 'github',
		repo_url: '',
		branch: 'main',
		token: '',
		showToken: false,
		sync_interval: 30,
		auto_pr: false
	});

	const activeCompanyId = $derived(companyStore.active?.id);

	async function loadGit() {
		gitLoading = true;
		try {
			const [cfg, logs] = await Promise.all([gitApi.config(activeCompanyId), gitApi.logs(10)]);
			gitConfig = cfg;
			gitLogs = logs;
		} finally {
			gitLoading = false;
		}
	}

	async function connectGit() {
		gitConnecting = true;
		gitError = '';
		try {
			gitConfig = await gitApi.connect({
				provider: gitForm.provider,
				repo_url: gitForm.repo_url.trim(),
				branch: gitForm.branch.trim() || 'main',
				token: gitForm.token.trim(),
				sync_interval: gitForm.sync_interval,
				auto_pr: gitForm.auto_pr
			}, activeCompanyId);
			gitForm = { provider: 'github', repo_url: '', branch: 'main', token: '', showToken: false, sync_interval: 30, auto_pr: false };
		} catch {
			gitError = t('settings_git_connect_err');
		} finally {
			gitConnecting = false;
		}
	}

	async function disconnectGit() {
		gitDisconnecting = true;
		try {
			await gitApi.disconnect(activeCompanyId);
			gitConfig = null;
			gitLogs = [];
		} finally {
			gitDisconnecting = false;
		}
	}

	async function triggerSync(direction: 'pull' | 'push') {
		gitSyncing = direction;
		gitError = '';
		try {
			const log = direction === 'pull'
				? await gitApi.pull(activeCompanyId)
				: await gitApi.push(undefined, activeCompanyId);
			gitLogs = [log, ...gitLogs].slice(0, 10);
			gitConfig = await gitApi.config(activeCompanyId);
		} catch {
			gitError = `${direction === 'pull' ? 'Pull' : 'Push'} ${t('settings_git_sync_err')}`;
		} finally {
			gitSyncing = null;
		}
	}

	// ── Audit log state ───────────────────────────────────────────────────────
	let auditLogs = $state<any[]>([]);
	let auditLoading = $state(false);
	let auditEntityFilter = $state('');

	async function loadAuditLogs() {
		auditLoading = true;
		try {
			const company = companyStore.active;
			const params = new URLSearchParams({ limit: '100' });
			if (company?.id) params.set('company_id', company.id);
			if (auditEntityFilter) params.set('entity_type', auditEntityFilter);
			const resp = await fetch(`${import.meta.env.VITE_API_URL}/audit?${params}`);
			auditLogs = await resp.json();
		} finally {
			auditLoading = false;
		}
	}

	// ── Backup state ─────────────────────────────────────────────────────────
	type BackupConfig = {
		configured: boolean;
		endpoint_url: string | null;
		bucket: string | null;
		prefix: string | null;
		region: string | null;
		access_key_hint: string | null;
	};
	type BackupEntry = { ts: string; filename: string; size_bytes: number; status: string; message: string | null };

	let backupConfig = $state<BackupConfig | null>(null);
	let backupHistory = $state<BackupEntry[]>([]);
	let backupLoading = $state(false);
	let backupSaving = $state(false);
	let backupRunning = $state(false);
	let backupError = $state('');
	let backupSuccess = $state('');
	let showEditForm = $state(false);
	let showSecret = $state(false);

	let backupForm = $state({
		endpoint_url: '',
		bucket: '',
		prefix: 'backups/',
		region: 'us-east-1',
		access_key: '',
		secret_key: '',
	});

	async function loadBackup() {
		backupLoading = true;
		try {
			const [cfg, hist] = await Promise.all([
				api.get<BackupConfig>('/backup/config'),
				api.get<BackupEntry[]>('/backup/history'),
			]);
			backupConfig = cfg;
			backupHistory = hist;
			if (cfg.configured) {
				backupForm.endpoint_url = cfg.endpoint_url ?? '';
				backupForm.bucket = cfg.bucket ?? '';
				backupForm.prefix = cfg.prefix ?? 'backups/';
				backupForm.region = cfg.region ?? 'us-east-1';
			}
		} finally {
			backupLoading = false;
		}
	}

	async function saveBackupConfig() {
		backupSaving = true;
		backupError = '';
		backupSuccess = '';
		try {
			await api.put('/backup/config', { ...backupForm });
			await loadBackup();
			showEditForm = false;
			backupSuccess = t('settings_backup_saved');
		} catch (e: any) {
			backupError = e?.message ?? t('settings_backup_save_failed');
		} finally {
			backupSaving = false;
		}
	}

	async function deleteBackupConfig() {
		backupError = '';
		try {
			await api.delete('/backup/config');
			backupConfig = { configured: false, endpoint_url: null, bucket: null, prefix: null, region: null, access_key_hint: null };
			backupForm = { endpoint_url: '', bucket: '', prefix: 'backups/', region: 'us-east-1', access_key: '', secret_key: '' };
			showEditForm = false;
		} catch (e: any) {
			backupError = e?.message ?? 'Silme başarısız';
		}
	}

	async function runBackup() {
		backupRunning = true;
		backupError = '';
		backupSuccess = '';
		try {
			const result = await api.post<{ filename: string; size_bytes: number }>('/backup/now', {});
			backupSuccess = `Yedek oluşturuldu: ${result.filename} (${(result.size_bytes / 1024).toFixed(1)} KB)`;
			await loadBackup();
		} catch (e: any) {
			backupError = e?.message ?? t('settings_backup_save_failed');
		} finally {
			backupRunning = false;
		}
	}

	// ── Social Media state ───────────────────────────────────────────────────
	type SocialConfig = {
		instagram_configured: boolean;
		ig_user_id: string | null;
		whatsapp_configured: boolean;
		wa_phone_number_id: string | null;
		wa_default_to: string | null;
	};

	let socialConfig = $state<SocialConfig | null>(null);
	let socialLoading = $state(false);
	let socialSaving = $state(false);
	let socialError = $state('');
	let socialSuccess = $state('');
	let showIgToken = $state(false);
	let showWaToken = $state(false);

	let socialForm = $state({
		ig_user_id: '',
		ig_access_token: '',
		wa_phone_number_id: '',
		wa_access_token: '',
		wa_default_to: '',
	});

	async function loadSocial() {
		socialLoading = true;
		try {
			const cfg = await api.get<SocialConfig>('/social-media/config');
			socialConfig = cfg;
			socialForm.ig_user_id = cfg.ig_user_id ?? '';
			socialForm.wa_phone_number_id = cfg.wa_phone_number_id ?? '';
			socialForm.wa_default_to = cfg.wa_default_to ?? '';
		} finally {
			socialLoading = false;
		}
	}

	async function saveSocial() {
		socialSaving = true;
		socialError = '';
		socialSuccess = '';
		try {
			await api.put('/social-media/config', { ...socialForm });
			await loadSocial();
			socialSuccess = 'Sosyal medya ayarları kaydedildi.';
		} catch (e: any) {
			socialError = e?.message ?? t('settings_backup_save_failed');
		} finally {
			socialSaving = false;
		}
	}

	async function deleteSocial() {
		socialError = '';
		try {
			await api.delete('/social-media/config');
			socialConfig = {
				instagram_configured: false, ig_user_id: null,
				whatsapp_configured: false, wa_phone_number_id: null, wa_default_to: null
			};
			socialForm = { ig_user_id: '', ig_access_token: '', wa_phone_number_id: '', wa_access_token: '', wa_default_to: '' };
		} catch (e: any) {
			socialError = e?.message ?? 'Silme başarısız';
		}
	}

	// ── Telegram state ───────────────────────────────────────────────────────
	let tgConfig = $state<TelegramConfigResponse | null>(null);
	let tgLoading = $state(false);
	let tgSaving = $state(false);
	let tgTesting = $state(false);
	let tgDeleting = $state(false);
	let tgError = $state('');
	let tgSuccess = $state('');
	let tgShowToken = $state(false);
	let tgEditMode = $state(false);
	let tgForm = $state({ bot_token: '', admin_chat_id: '' });

	async function loadTelegram() {
		tgLoading = true;
		tgError = '';
		try {
			tgConfig = await telegramApi.getConfig();
		} catch (e: any) {
			tgError = e?.message ?? 'Yüklenemedi';
		} finally {
			tgLoading = false;
		}
	}

	async function saveTelegram() {
		tgSaving = true;
		tgError = '';
		tgSuccess = '';
		try {
			const res = await telegramApi.saveConfig(tgForm.bot_token.trim(), tgForm.admin_chat_id.trim());
			tgConfig = res;
			tgForm = { bot_token: '', admin_chat_id: '' };
			tgEditMode = false;
			tgSuccess = `${t('tg_connected')} — @${res.bot_username ?? 'bot'}`;
		} catch (e: any) {
			tgError = e?.message ?? 'Kaydetme başarısız';
		} finally {
			tgSaving = false;
		}
	}

	async function testTelegram() {
		tgTesting = true;
		tgError = '';
		tgSuccess = '';
		try {
			await telegramApi.test();
			tgSuccess = 'Test mesajı gönderildi ✓';
		} catch (e: any) {
			tgError = e?.message ?? 'Test başarısız';
		} finally {
			tgTesting = false;
		}
	}

	async function deleteTelegram() {
		tgDeleting = true;
		tgError = '';
		try {
			await telegramApi.deleteConfig();
			tgConfig = { configured: false };
			tgSuccess = '';
		} catch (e: any) {
			tgError = e?.message ?? 'Silinemedi';
		} finally {
			tgDeleting = false;
		}
	}

	// ── Database state ───────────────────────────────────────────────────────
	type DBConn = {
		id: string; name: string; db_type: string; status: string;
		last_checked: string | null; created_at: string;
		schema?: { tables: Record<string, {
			description: string; row_count: number;
			columns: Record<string, { type: string; nullable: boolean; primary_key: boolean; foreign_key: string | null; description: string }>;
		}> };
		examples?: Array<{ sql: string; description: string }>;
	};

	let databases = $state<DBConn[]>([]);
	let dbLoading = $state(false);
	let dbError = $state('');
	let dbSuccess = $state('');
	let showAddDB = $state(false);
	let discoveringId = $state<string | null>(null);
	let selectedDB = $state<DBConn | null>(null);

	let dbForm = $state({ name: '', db_type: 'postgresql', dsn: '' });

	async function loadDatabases() {
		dbLoading = true;
		try {
			databases = await api.get<DBConn[]>('/databases/');
		} catch (e: any) {
			dbError = e?.message ?? 'Yüklenemedi';
		} finally {
			dbLoading = false;
		}
	}

	async function addDatabase() {
		dbError = '';
		try {
			await api.post('/databases/', { ...dbForm });
			dbForm = { name: '', db_type: 'postgresql', dsn: '' };
			showAddDB = false;
			dbSuccess = 'Veritabanı eklendi.';
			await loadDatabases();
		} catch (e: any) {
			dbError = e?.message ?? 'Eklenemedi';
		}
	}

	async function deleteDatabase(id: string) {
		try {
			await api.delete(`/databases/${id}`);
			if (selectedDB?.id === id) selectedDB = null;
			await loadDatabases();
		} catch (e: any) {
			dbError = e?.message ?? 'Silinemedi';
		}
	}

	async function discoverSchema(id: string) {
		discoveringId = id;
		dbError = '';
		try {
			const updated = await api.post<DBConn>(`/databases/${id}/discover`, {});
			databases = databases.map(d => d.id === id ? updated : d);
			if (selectedDB?.id === id) selectedDB = updated;
			dbSuccess = 'Şema keşfedildi.';
		} catch (e: any) {
			dbError = e?.message ?? 'Şema keşfedilemedi';
		} finally {
			discoveringId = null;
		}
	}

	async function saveAnnotations() {
		if (!selectedDB) return;
		try {
			await api.patch(`/databases/${selectedDB.id}/annotate`, {
				schema_json: JSON.stringify(selectedDB.schema),
				examples_json: JSON.stringify(selectedDB.examples ?? []),
			});
			dbSuccess = t('db_save_annotations');
		} catch (e: any) {
			dbError = e?.message ?? 'Kaydedilemedi';
		}
	}

	function switchTab(newTab: 'providers' | 'git' | 'audit' | 'backup' | 'social' | 'databases') {
		tab = newTab;
		if (newTab === 'audit') loadAuditLogs();
		if (newTab === 'backup') loadBackup();
		if (newTab === 'social') { loadSocial(); loadTelegram(); }
		if (newTab === 'databases') loadDatabases();
	}

	// ── Helpers ───────────────────────────────────────────────────────────────
	function relativeTime(iso: string | null): string {
		if (!iso) return '—';
		const diff = Date.now() - new Date(iso).getTime();
		const min = Math.floor(diff / 60000);
		if (min < 1) return 'az önce';
		if (min < 60) return `${min} dakika önce`;
		const h = Math.floor(min / 60);
		if (h < 24) return `${h} saat önce`;
		return `${Math.floor(h / 24)} gün önce`;
	}

	function shortSha(sha: string | null) {
		return sha ? sha.slice(0, 7) : '—';
	}

	async function loadOnboardingStatus() {
		const id = companyStore.active?.id;
		if (!id) return;
		try {
			const res = await onboardingApi.status(id);
			aiOnboarded = res.ai_onboarded;
		} catch { aiOnboarded = false; }
	}

	function startOnboarding() {
		const company = companyStore.active;
		if (!company) return;
		const params = new URLSearchParams({ company_id: company.id, company_name: company.name });
		goto(`/onboarding?${params}`);
	}

	onMount(() => {
		loadProviders();
		loadGit();
		loadOnboardingStatus();
	});
</script>

<svelte:head><title>{t('settings_title')} • fab.engineering</title></svelte:head>

<div class="max-w-3xl mx-auto">
	<!-- Header -->
	<div class="flex items-center gap-x-3 mb-8">
		<div class="w-10 h-10 rounded-xl bg-muted flex items-center justify-center">
			<Settings class="w-5 h-5 text-muted-foreground" />
		</div>
		<div>
			<h1 class="text-2xl font-bold tracking-tight">{t('settings_title')}</h1>
			<p class="text-sm text-muted-foreground">{t('settings_subtitle')}</p>
		</div>
	</div>

	<!-- Tabs -->
	<div class="relative mb-8">
		<div class="absolute bottom-0 left-0 right-0 h-px bg-border pointer-events-none"></div>
		<div class="flex gap-x-1" style="overflow-x:auto; scrollbar-width:none; -ms-overflow-style:none;">

			<button class={['tab-btn', tab==='providers' ? 'tab-active' : 'tab-inactive'].join(' ')} onclick={() => switchTab('providers')}>
				<Cpu class="w-4 h-4" />{t('settings_providers')}
			</button>
			<button class={['tab-btn', tab==='git' ? 'tab-active' : 'tab-inactive'].join(' ')} onclick={() => switchTab('git')}>
				<GitBranch class="w-4 h-4" />{t('settings_git')}
			</button>
			<button class={['tab-btn', tab==='audit' ? 'tab-active' : 'tab-inactive'].join(' ')} onclick={() => switchTab('audit')}>
				<Clock class="w-4 h-4" />{t('settings_audit_tab')}
			</button>
			<button class={['tab-btn', tab==='backup' ? 'tab-active' : 'tab-inactive'].join(' ')} onclick={() => switchTab('backup')}>
				<Database class="w-4 h-4" />{t('settings_backup_tab')}
			</button>
			<button class={['tab-btn', tab==='social' ? 'tab-active' : 'tab-inactive'].join(' ')} onclick={() => switchTab('social')}>
				<Link class="w-4 h-4" />{t('settings_integrations_tab')}
			</button>
			<button class={['tab-btn', tab==='databases' ? 'tab-active' : 'tab-inactive'].join(' ')} onclick={() => switchTab('databases')}>
				<Table2 class="w-4 h-4" />{t('settings_databases_tab')}
				{#if tab !== 'databases'}
					<span class="w-1.5 h-1.5 rounded-full bg-primary animate-pulse flex-shrink-0" title="Database connections"></span>
				{/if}
			</button>

		</div>
	</div>

	<!-- ── Provider card snippet (reused for local and cloud sections) ─── -->
	{#snippet providerCard(card: ProviderCard, isActive: boolean, isInvalid: boolean, isUnconfigured: boolean, isLocal: boolean, showForm: boolean)}
		<div class={[
			'rounded-2xl border bg-card transition-all',
			isActive   ? 'border-emerald-500/30' :
			isInvalid  ? 'border-destructive/30'  :
			             'border-dashed border-border/60 opacity-80'
		].join(' ')}>
			<!-- Header row -->
			<div class="flex items-center justify-between px-5 py-4">
				<div class="flex items-center gap-x-3">
					{#if isActive}
						<CheckCircle2 class="w-5 h-5 text-emerald-500 flex-shrink-0" />
					{:else if isInvalid}
						<AlertTriangle class="w-5 h-5 text-destructive flex-shrink-0" />
					{:else}
						<div class="w-5 h-5 rounded-full border-2 border-border flex-shrink-0"></div>
					{/if}
					<div>
						<div class="font-semibold text-sm">{card.display_name}</div>
						{#if isActive}
							<div class="text-xs text-muted-foreground mt-0.5">
								{t('settings_provider_last_tested')} {relativeTime(card.last_tested)}
							</div>
						{:else if isInvalid}
							<div class="text-xs text-destructive mt-0.5">{t('settings_provider_invalid')}</div>
						{:else if isLocal}
							<div class="text-xs text-muted-foreground mt-0.5">{t('settings_provider_local_hint')}</div>
						{:else}
							<div class="text-xs text-muted-foreground mt-0.5">{t('settings_provider_not_connected')}</div>
						{/if}
					</div>
				</div>
				<div class="flex items-center gap-x-2">
					{#if isActive}
						<Button variant="ghost" size="sm" class="h-8 px-3 text-xs"
							onclick={() => (card.editMode = !card.editMode)}>
							{isLocal ? t('settings_provider_update_url') : t('settings_provider_update_key')}
						</Button>
						<Button variant="ghost" size="sm" class="h-8 px-3 text-xs gap-x-1.5"
							disabled={card.testing} onclick={() => testKey(card)}>
							{#if card.testing}<Loader2 class="w-3.5 h-3.5 animate-spin" />{:else}<RefreshCw class="w-3.5 h-3.5" />{/if}
							{t('settings_provider_test')}
						</Button>
					{/if}
					{#if isActive || isInvalid}
						<Button variant="ghost" size="sm"
							class="h-8 px-3 text-xs text-destructive hover:text-destructive gap-x-1.5"
							disabled={card.deleting} onclick={() => deleteKey(card)}>
							{#if card.deleting}<Loader2 class="w-3.5 h-3.5 animate-spin" />{:else}<Trash2 class="w-3.5 h-3.5" />{/if}
							{t('settings_provider_delete')}
						</Button>
					{:else if isUnconfigured}
						<Button size="sm" class="h-8 px-4 text-xs"
							onclick={() => (card.connectMode = !card.connectMode)}>
							{card.connectMode ? t('cancel') : t('settings_connect_btn')}
						</Button>
					{/if}
				</div>
			</div>
			<!-- Model chips -->
			{#if isActive && card.models.length > 0}
				<div class="px-5 pb-3 flex flex-wrap gap-1.5">
					{#each card.models as model}
						<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-500/20">
							{model.name}
						</span>
					{/each}
				</div>
			{/if}
			<!-- Connect / update form -->
			{#if showForm}
				<div class="px-5 pb-4 pt-1 border-t border-border/50 space-y-3">
					{#if card.error}
						<div class="text-xs text-destructive flex items-center gap-x-1.5">
							<XCircle class="w-3.5 h-3.5 flex-shrink-0" />{card.error}
						</div>
					{/if}
					{#if isLocal}
						<div>
							<label class="block text-xs font-medium text-muted-foreground mb-1.5">{t('settings_provider_base_url')}</label>
							<div class="flex gap-x-2">
								<input type="text" bind:value={card.urlInput}
									placeholder={LOCAL_PROVIDER_DEFAULTS[card.provider]}
									class="flex-1 h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring"
									onkeydown={(e) => e.key === 'Enter' && connectProvider(card)} />
								<Button size="sm" class="h-9 px-4 text-xs" disabled={card.saving}
									onclick={() => connectProvider(card)}>
									{#if card.saving}<Loader2 class="w-3.5 h-3.5 animate-spin mr-1" />{/if}
									{card.saving ? t('settings_provider_testing') : t('settings_connect_btn')}
								</Button>
							</div>
						</div>
					{:else}
						<div class="flex gap-x-2">
							<div class="relative flex-1">
								<input type={card.showKey ? 'text' : 'password'}
									bind:value={card.keyInput}
									placeholder={t('settings_provider_key_ph')}
									class="w-full h-9 px-3 pr-10 text-sm rounded-lg border border-input bg-background placeholder:text-muted-foreground font-mono focus:outline-none focus:ring-2 focus:ring-ring"
									onkeydown={(e) => e.key === 'Enter' && (isUnconfigured ? connectProvider(card) : saveKey(card))} />
								<button class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
									onclick={() => (card.showKey = !card.showKey)} type="button" tabindex="-1">
									{#if card.showKey}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
								</button>
							</div>
							<Button size="sm" class="h-9 px-4 text-xs"
								disabled={card.saving || !card.keyInput.trim()}
								onclick={() => isUnconfigured ? connectProvider(card) : saveKey(card)}>
								{#if card.saving}<Loader2 class="w-3.5 h-3.5 animate-spin mr-1" />{/if}
								{card.saving ? t('settings_provider_testing') : t('settings_provider_save_test')}
							</Button>
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{/snippet}

	<!-- ── PROVIDERS TAB ─────────────────────────────────────────────────── -->
	{#if tab === 'providers'}
		<div class="space-y-4">

			{#if providerLoading}
				<div class="flex items-center gap-x-2 text-muted-foreground py-12 justify-center">
					<Loader2 class="w-4 h-4 animate-spin" />
					<span class="text-sm">{t('loading')}</span>
				</div>
			{:else}
				<!-- ── Local Models ──────────────────────────────────────────── -->
				<div class="space-y-3">
					<div class="flex items-center gap-2">
						<Server class="w-4 h-4 text-muted-foreground" />
						<span class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{t('settings_local_providers')}</span>
						<span class="text-xs text-muted-foreground">— {t('settings_local_providers_desc')}</span>
					</div>
					{#each providerCards.filter(c => LOCAL_PROVIDER_SLUGS.has(c.provider)) as card (card.provider)}
						{@const isActive = card.status === 'active'}
						{@const isInvalid = card.status === 'invalid'}
						{@const isUnconfigured = card.status === 'unconfigured'}
						{@const isLocal = true}
						{@const showForm = card.connectMode || card.editMode || isInvalid}
						{@render providerCard(card, isActive, isInvalid, isUnconfigured, isLocal, showForm)}
					{/each}
				</div>

				<!-- ── Cloud API Services ─────────────────────────────────────── -->
				<div class="space-y-3 mt-8">
					<div class="flex items-center gap-2">
						<Globe class="w-4 h-4 text-muted-foreground" />
						<span class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{t('settings_cloud_providers')}</span>
						<span class="text-xs text-muted-foreground">— {t('settings_cloud_providers_desc')}</span>
					</div>
					{#each providerCards.filter(c => !LOCAL_PROVIDER_SLUGS.has(c.provider)) as card (card.provider)}
						{@const isActive = card.status === 'active'}
						{@const isInvalid = card.status === 'invalid'}
						{@const isUnconfigured = card.status === 'unconfigured'}
						{@const isLocal = false}
						{@const showForm = card.connectMode || card.editMode || isInvalid}
						{@render providerCard(card, isActive, isInvalid, isUnconfigured, isLocal, showForm)}
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	<!-- ── AI ONBOARDING BANNER ─────────────────────────────────────────── -->
	{#if tab === 'providers' && aiOnboarded === false}
		<div class="mt-6 rounded-2xl border border-primary/20 bg-primary/5 p-5 flex items-start justify-between gap-4">
			<div class="flex items-start gap-3">
				<div class="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
					<Sparkles class="w-4 h-4 text-primary" />
				</div>
				<div>
					<div class="font-semibold text-sm mb-1">{t('settings_ai_setup_title')}</div>
					<p class="text-xs text-muted-foreground leading-relaxed max-w-sm">
						{t('settings_ai_setup_desc')}
					</p>
				</div>
			</div>
			<button
				onclick={startOnboarding}
				disabled={onboardingLoading}
				class="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
			>
				<Sparkles class="w-4 h-4" />
				{t('settings_ai_setup_btn')}
			</button>
		</div>
	{/if}

	<!-- ── GIT TAB ────────────────────────────────────────────────────────── -->
	{#if tab === 'git'}
		{#if gitLoading}
			<div class="flex items-center gap-x-2 text-muted-foreground py-12 justify-center">
				<Loader2 class="w-4 h-4 animate-spin" />
				<span class="text-sm">{t('loading')}</span>
			</div>
		{:else if gitConfig}
			<!-- Connected state -->
			<div class="rounded-2xl border bg-card">
				<div class="flex items-center justify-between px-5 py-4">
					<div class="flex items-center gap-x-3">
						<CheckCircle2 class="w-5 h-5 text-emerald-500" />
						<div>
							<div class="font-semibold text-sm capitalize">{gitConfig.provider}</div>
							<div class="text-xs text-muted-foreground font-mono mt-0.5 max-w-xs truncate">
								{gitConfig.repo_url}
							</div>
						</div>
					</div>
					<div class="flex items-center gap-x-2">
						<span class="text-xs text-muted-foreground px-2 py-1 bg-muted rounded-lg font-mono">
							{gitConfig.branch}
						</span>
						<Button
							variant="ghost"
							size="sm"
							class="h-8 px-3 text-xs text-destructive hover:text-destructive gap-x-1.5"
							disabled={gitDisconnecting}
							onclick={disconnectGit}
						>
							{#if gitDisconnecting}
								<Loader2 class="w-3.5 h-3.5 animate-spin" />
							{:else}
								<Unlink class="w-3.5 h-3.5" />
							{/if}
							{t('settings_git_disconnect')}
						</Button>
					</div>
				</div>

				<!-- Stats row -->
				<div class="px-5 pb-4 grid grid-cols-3 gap-4 border-t border-border/50 pt-4">
					<div>
						<div class="text-xs text-muted-foreground">{t('settings_git_last_sync')}</div>
						<div class="text-sm font-medium mt-0.5">{relativeTime(gitConfig.last_synced)}</div>
					</div>
					<div>
						<div class="text-xs text-muted-foreground">{t('settings_git_last_commit')}</div>
						<div class="text-sm font-mono font-medium mt-0.5">{shortSha(gitConfig.last_commit_sha)}</div>
					</div>
					<div>
						<div class="text-xs text-muted-foreground">{t('settings_git_status')}</div>
						<div class={['text-sm font-medium mt-0.5', gitConfig.status === 'connected' ? 'text-emerald-600' : 'text-destructive'].join(' ')}>
							{gitConfig.status === 'connected' ? t('settings_git_connected') : gitConfig.status}
						</div>
					</div>
				</div>

				<!-- Sync actions -->
				<div class="px-5 pb-4 flex items-center gap-x-2 border-t border-border/50 pt-4">
					{#if gitError}
						<p class="text-xs text-destructive flex-1 flex items-center gap-x-1.5">
							<XCircle class="w-3.5 h-3.5" /> {gitError}
						</p>
					{/if}
					<div class="flex gap-x-2 ml-auto">
						<Button
							variant="outline"
							size="sm"
							class="h-8 px-3 text-xs gap-x-1.5"
							disabled={gitSyncing !== null}
							onclick={() => triggerSync('pull')}
						>
							{#if gitSyncing === 'pull'}
								<Loader2 class="w-3.5 h-3.5 animate-spin" />
							{:else}
								<ArrowDown class="w-3.5 h-3.5" />
							{/if}
							{t('settings_git_pull')}
						</Button>
						<Button
							variant="outline"
							size="sm"
							class="h-8 px-3 text-xs gap-x-1.5"
							disabled={gitSyncing !== null}
							onclick={() => triggerSync('push')}
						>
							{#if gitSyncing === 'push'}
								<Loader2 class="w-3.5 h-3.5 animate-spin" />
							{:else}
								<ArrowUp class="w-3.5 h-3.5" />
							{/if}
							{t('settings_git_push')}
						</Button>
					</div>
				</div>
			</div>

			<!-- Sync logs -->
			{#if gitLogs.length > 0}
				<div class="mt-6">
					<h3 class="text-sm font-semibold mb-3 text-muted-foreground tracking-wide uppercase text-xs">
						{t('settings_git_sync_history')}
					</h3>
					<div class="rounded-xl border overflow-hidden">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b bg-muted/40">
									<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">{t('settings_git_col_dir')}</th>
									<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">{t('settings_git_col_status')}</th>
									<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">{t('settings_git_col_files')}</th>
									<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">{t('settings_git_col_commit')}</th>
									<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">{t('settings_git_col_message')}</th>
									<th class="text-right px-4 py-2.5 text-xs font-medium text-muted-foreground">{t('settings_git_col_time')}</th>
								</tr>
							</thead>
							<tbody>
								{#each gitLogs as log}
									<tr class="border-b last:border-0 hover:bg-muted/30 transition-colors">
										<td class="px-4 py-2.5">
											<span class="flex items-center gap-x-1.5 text-xs font-medium">
												{#if log.direction === 'pull'}
													<ArrowDown class="w-3.5 h-3.5 text-blue-500" />
													Pull
												{:else}
													<ArrowUp class="w-3.5 h-3.5 text-purple-500" />
													Push
												{/if}
											</span>
										</td>
										<td class="px-4 py-2.5">
											<span class={[
												'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
												log.status === 'success'    ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400' :
												log.status === 'error'      ? 'bg-destructive/10 text-destructive' :
												                              'bg-muted text-muted-foreground'
											].join(' ')}>
												{log.status === 'success' ? t('settings_git_success') : log.status === 'error' ? t('settings_git_error') : t('settings_git_no_change')}
											</span>
										</td>
										<td class="px-4 py-2.5 text-xs text-muted-foreground">{log.files_changed}</td>
										<td class="px-4 py-2.5 font-mono text-xs text-muted-foreground">{shortSha(log.commit_sha)}</td>
										<td class="px-4 py-2.5 text-xs text-muted-foreground max-w-xs truncate">{log.message ?? '—'}</td>
										<td class="px-4 py-2.5 text-xs text-muted-foreground text-right">{relativeTime(log.created_at)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		{:else}
			<!-- Connect form -->
			<div class="mb-4">
				<p class="text-sm text-muted-foreground">
					{t('settings_git_desc')}
				</p>
			</div>

			<div class="rounded-2xl border bg-card p-5 space-y-4">
				<h3 class="font-semibold text-sm flex items-center gap-x-2">
					<Link class="w-4 h-4" />
					{t('settings_git_new_conn')}
				</h3>

				{#if gitError}
					<div class="text-xs text-destructive flex items-center gap-x-1.5 bg-destructive/10 px-3 py-2 rounded-lg">
						<XCircle class="w-3.5 h-3.5" /> {gitError}
					</div>
				{/if}

				<div class="grid grid-cols-2 gap-3">
					<div>
						<label class="block text-xs font-medium text-muted-foreground mb-1.5">{t('settings_git_provider_label')}</label>
						<select
							bind:value={gitForm.provider}
							class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring"
						>
							<option value="github">GitHub</option>
							<option value="gitlab">GitLab</option>
							<option value="gitea">Gitea</option>
						</select>
					</div>
					<div>
						<label class="block text-xs font-medium text-muted-foreground mb-1.5">{t('settings_git_branch_label')}</label>
						<input
							type="text"
							bind:value={gitForm.branch}
							placeholder="main"
							class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring font-mono"
						/>
					</div>
				</div>

				<div>
					<label class="block text-xs font-medium text-muted-foreground mb-1.5">{t('settings_git_repo_label')}</label>
					<input
						type="url"
						bind:value={gitForm.repo_url}
						placeholder="https://github.com/organization/ai-capabilities"
						class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring"
					/>
				</div>

				<div>
					<label class="block text-xs font-medium text-muted-foreground mb-1.5">
						{t('settings_git_token_label')}
						<span class="font-normal text-muted-foreground/70">
							({gitForm.provider === 'github' ? 'ghp_...' : 'glpat-...'})
						</span>
					</label>
					<div class="relative">
						<input
							type={gitForm.showToken ? 'text' : 'password'}
							bind:value={gitForm.token}
							placeholder={t('settings_git_token_ph')}
							class="w-full h-9 px-3 pr-10 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring"
						/>
						<button
							class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
							onclick={() => (gitForm.showToken = !gitForm.showToken)}
							type="button"
						>
							{#if gitForm.showToken}
								<EyeOff class="w-4 h-4" />
							{:else}
								<Eye class="w-4 h-4" />
							{/if}
						</button>
					</div>
				</div>

				<div class="flex items-center justify-between pt-1">
					<label class="flex items-center gap-x-2 text-sm cursor-pointer select-none">
						<input type="checkbox" bind:checked={gitForm.auto_pr} class="rounded" />
						<span>{t('settings_git_auto_pr')}</span>
					</label>
					<Button
						variant="default"
						size="sm"
						class="h-9 px-5"
						disabled={gitConnecting || !gitForm.repo_url.trim() || !gitForm.token.trim()}
						onclick={connectGit}
					>
						{#if gitConnecting}
							<Loader2 class="w-3.5 h-3.5 animate-spin mr-1.5" />
							{t('settings_git_connecting')}
						{:else}
							<Link class="w-3.5 h-3.5 mr-1.5" />
							{t('settings_git_connect')}
						{/if}
					</Button>
				</div>
			</div>
		{/if}
	{/if}

	<!-- ── BACKUP TAB ───────────────────────────────────────────────────── -->
	{#if tab === 'backup'}
		<div class="space-y-6">
			<p class="text-sm text-muted-foreground">{t('settings_backup_desc')}</p>

			{#if backupError}
				<div class="flex items-center gap-x-2 text-sm text-destructive bg-destructive/10 px-4 py-3 rounded-xl">
					<XCircle class="w-4 h-4 flex-shrink-0" />
					{backupError}
				</div>
			{/if}
			{#if backupSuccess}
				<div class="flex items-center gap-x-2 text-sm text-emerald-700 bg-emerald-50 px-4 py-3 rounded-xl">
					<CheckCircle2 class="w-4 h-4 flex-shrink-0" />
					{backupSuccess}
				</div>
			{/if}

			{#if backupLoading}
				<div class="flex justify-center py-12">
					<Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
				</div>
			{:else}
				<!-- Config card -->
				<div class="rounded-2xl border bg-card overflow-hidden">
					<div class="flex items-center justify-between px-5 py-4">
						<div class="flex items-center gap-x-3">
							{#if backupConfig?.configured}
								<ShieldCheck class="w-5 h-5 text-emerald-500" />
								<div>
									<div class="font-semibold text-sm">{backupConfig.bucket}</div>
									<div class="text-xs text-muted-foreground mt-0.5">
										{backupConfig.endpoint_url || 'AWS S3'} · {backupConfig.prefix}
									</div>
								</div>
							{:else}
								<Database class="w-5 h-5 text-muted-foreground/50" />
								<div>
									<div class="font-semibold text-sm text-muted-foreground">{t('settings_backup_unconfigured')}</div>
									<div class="text-xs text-muted-foreground mt-0.5">{t('settings_backup_unconfigured_desc')}</div>
								</div>
							{/if}
						</div>
						<div class="flex items-center gap-x-2">
							{#if backupConfig?.configured}
								<Button
									variant="default"
									size="sm"
									class="h-8 px-3 text-xs gap-x-1.5"
									disabled={backupRunning}
									onclick={runBackup}
								>
									{#if backupRunning}
										<Loader2 class="w-3.5 h-3.5 animate-spin" />
										{t('settings_backup_running')}
									{:else}
										<CloudUpload class="w-3.5 h-3.5" />
										{t('settings_backup_now')}
									{/if}
								</Button>
								<Button
									variant="ghost"
									size="sm"
									class="h-8 px-3 text-xs gap-x-1.5"
									onclick={() => { showEditForm = !showEditForm; }}
								>
									{t('settings_backup_edit')}
								</Button>
								<Button
									variant="ghost"
									size="sm"
									class="h-8 px-3 text-xs text-destructive hover:text-destructive gap-x-1.5"
									onclick={deleteBackupConfig}
								>
									<Trash2 class="w-3.5 h-3.5" />
								</Button>
							{:else}
								<Button
									variant="outline"
									size="sm"
									class="h-8 px-3 text-xs gap-x-1.5"
									onclick={() => { showEditForm = true; }}
								>
									<Link class="w-3.5 h-3.5" />
									{t('settings_backup_configure')}
								</Button>
							{/if}
						</div>
					</div>

					{#if showEditForm || !backupConfig?.configured}
						<div class="px-5 pb-5 pt-2 border-t border-border/50 space-y-3">
							<div class="grid grid-cols-2 gap-3">
								<div>
									<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="backup-bucket">
										Bucket Adı <span class="text-destructive">*</span>
									</label>
									<input id="backup-bucket" type="text" bind:value={backupForm.bucket}
										placeholder="my-backups"
										class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
								</div>
								<div>
									<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="backup-prefix">
										Prefix
									</label>
									<input id="backup-prefix" type="text" bind:value={backupForm.prefix}
										placeholder="backups/"
										class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
								</div>
							</div>
							<div>
								<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="backup-endpoint">
									Endpoint URL
									<span class="font-normal text-muted-foreground/70">(boş = AWS S3; R2/MinIO için doldurun)</span>
								</label>
								<input id="backup-endpoint" type="url" bind:value={backupForm.endpoint_url}
									placeholder="https://xxx.r2.cloudflarestorage.com"
									class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
							</div>
							<div class="grid grid-cols-2 gap-3">
								<div>
									<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="backup-ak">
										Access Key ID <span class="text-destructive">*</span>
									</label>
									<input id="backup-ak" type="text" bind:value={backupForm.access_key}
										placeholder="AKIAIOSFODNN7EXAMPLE"
										class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
								</div>
								<div>
									<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="backup-region">
										Region
									</label>
									<input id="backup-region" type="text" bind:value={backupForm.region}
										placeholder="us-east-1"
										class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
								</div>
							</div>
							<div>
								<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="backup-sk">
									Secret Access Key <span class="text-destructive">*</span>
									{#if backupConfig?.configured && !backupForm.secret_key}
										<span class="font-normal text-muted-foreground/70">(mevcut anahtar — değiştirmek için girin)</span>
									{/if}
								</label>
								<div class="relative">
									<input id="backup-sk" type={showSecret ? 'text' : 'password'}
										bind:value={backupForm.secret_key}
										placeholder={backupConfig?.configured ? '••••••••' : 'wJalrXUtnFEMI/K7MDENG...'}
										class="w-full h-9 px-3 pr-10 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
									<button type="button"
										class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
										onclick={() => (showSecret = !showSecret)}>
										{#if showSecret}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
									</button>
								</div>
							</div>
							<div class="flex justify-end gap-x-2 pt-1">
								{#if showEditForm}
									<Button variant="ghost" size="sm" class="h-8 px-3 text-xs"
										onclick={() => { showEditForm = false; }}>{t('cancel')}</Button>
								{/if}
								<Button variant="default" size="sm" class="h-8 px-4 text-xs"
									disabled={backupSaving || !backupForm.bucket || !backupForm.access_key || (!backupConfig?.configured && !backupForm.secret_key)}
									onclick={saveBackupConfig}>
									{#if backupSaving}
										<Loader2 class="w-3.5 h-3.5 animate-spin mr-1.5" />
									{/if}
									{t('save')}
								</Button>
							</div>
						</div>
					{/if}
				</div>

				<!-- Backup History -->
				{#if backupHistory.length > 0}
					<div>
						<h3 class="text-xs font-semibold text-muted-foreground tracking-wide uppercase mb-3 flex items-center gap-x-2">
							<History class="w-3.5 h-3.5" />
							{t('settings_backup_history_title')}
						</h3>
						<div class="rounded-xl border overflow-hidden">
							<table class="w-full text-sm">
								<thead>
									<tr class="border-b bg-muted/40">
										<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">Dosya</th>
										<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">Boyut</th>
										<th class="text-left px-4 py-2.5 text-xs font-medium text-muted-foreground">Durum</th>
										<th class="text-right px-4 py-2.5 text-xs font-medium text-muted-foreground">Tarih</th>
									</tr>
								</thead>
								<tbody>
									{#each backupHistory as entry}
										<tr class="border-b last:border-0 hover:bg-muted/30">
											<td class="px-4 py-2.5 font-mono text-xs">{entry.filename}</td>
											<td class="px-4 py-2.5 text-xs text-muted-foreground">
												{entry.size_bytes > 0 ? (entry.size_bytes / 1024).toFixed(1) + ' KB' : '—'}
											</td>
											<td class="px-4 py-2.5">
												<span class={[
													'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium',
													entry.status === 'success'
														? 'bg-emerald-500/10 text-emerald-700'
														: 'bg-destructive/10 text-destructive'
												].join(' ')}>
													{entry.status === 'success' ? t('settings_backup_status_ok') : t('error')}
												</span>
												{#if entry.message && entry.status !== 'success'}
													<span class="text-xs text-muted-foreground ml-2 truncate max-w-xs">{entry.message}</span>
												{/if}
											</td>
											<td class="px-4 py-2.5 text-xs text-muted-foreground text-right">
												{new Date(entry.ts).toLocaleString('tr-TR')}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</div>
				{/if}
			{/if}
		</div>
	{/if}

	<!-- ── DATABASES TAB ────────────────────────────────────────────────── -->
	{#if tab === 'databases'}
		<div class="space-y-5">
			<p class="text-sm text-muted-foreground">{t('db_tab_desc')}</p>

			{#if dbError}
				<div class="flex items-center gap-x-2 text-sm text-destructive bg-destructive/10 px-4 py-3 rounded-xl">
					<XCircle class="w-4 h-4 flex-shrink-0" />{dbError}
				</div>
			{/if}
			{#if dbSuccess}
				<div class="flex items-center gap-x-2 text-sm text-emerald-700 bg-emerald-50 px-4 py-3 rounded-xl">
					<CheckCircle2 class="w-4 h-4 flex-shrink-0" />{dbSuccess}
				</div>
			{/if}

			<!-- Add DB form -->
			{#if showAddDB}
				<div class="rounded-2xl border bg-card p-5 space-y-3">
					<div class="grid grid-cols-2 gap-3">
						<div>
							<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="db-name">{t('db_name_label')}</label>
							<input id="db-name" type="text" bind:value={dbForm.name} placeholder="Müşteri DB"
								class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring" />
						</div>
						<div>
							<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="db-type">{t('db_type_label')}</label>
							<select id="db-type" bind:value={dbForm.db_type} class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-2 focus:ring-ring">
								<option value="postgresql">PostgreSQL</option>
								<option value="mysql">MySQL / MariaDB</option>
								<option value="sqlite">SQLite</option>
							</select>
						</div>
					</div>
					<div>
						<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="db-dsn">
							{t('db_dsn_label')}
						</label>
						<input id="db-dsn" type="text" bind:value={dbForm.dsn}
							placeholder={dbForm.db_type === 'sqlite' ? '/data/mydb.db' : dbForm.db_type === 'postgresql' ? 'postgresql://user:pass@host:5432/dbname' : 'mysql+pymysql://user:pass@host/dbname'}
							class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
					</div>
					<div class="flex justify-end gap-x-2">
						<Button variant="ghost" size="sm" class="h-8 px-3 text-xs" onclick={() => showAddDB = false}>{t('cancel')}</Button>
						<Button variant="default" size="sm" class="h-8 px-4 text-xs"
							disabled={!dbForm.name.trim() || !dbForm.dsn.trim()}
							onclick={addDatabase}>{t('db_connect')}</Button>
					</div>
				</div>
			{/if}

			<!-- DB list -->
			{#if dbLoading}
				<div class="flex justify-center py-10"><Loader2 class="w-5 h-5 animate-spin text-muted-foreground" /></div>
			{:else if databases.length === 0 && !showAddDB}
				<div class="text-center py-12 text-muted-foreground">
					<Table2 class="w-8 h-8 mx-auto mb-3 opacity-30" />
					<p class="text-sm">Henüz veritabanı yok</p>
					<Button variant="outline" size="sm" class="mt-4 h-8 px-4 text-xs" onclick={() => showAddDB = true}>
						<Plus class="w-3.5 h-3.5 mr-1.5" /> Veritabanı Ekle
					</Button>
				</div>
			{:else}
				<div class="flex justify-between items-center">
					<span class="text-xs text-muted-foreground">{databases.length} {t('db_connections')}</span>
					<Button variant="outline" size="sm" class="h-8 px-3 text-xs" onclick={() => showAddDB = !showAddDB}>
						<Plus class="w-3.5 h-3.5 mr-1" /> Ekle
					</Button>
				</div>

				<div class="space-y-2">
					{#each databases as db}
						<div class="rounded-xl border bg-card overflow-hidden">
							<div class="flex items-center gap-x-3 px-4 py-3 cursor-pointer hover:bg-muted/30 transition-colors"
								onclick={() => selectedDB = (selectedDB?.id === db.id ? null : { ...db })}>
								<div class={['w-2 h-2 rounded-full flex-shrink-0',
									db.status === 'ok' ? 'bg-emerald-500' : 'bg-amber-400'].join(' ')}></div>
								<div class="flex-1 min-w-0">
									<div class="text-sm font-medium">{db.name}</div>
									<div class="text-xs text-muted-foreground">{db.db_type}
										{#if db.schema}· {Object.keys(db.schema.tables ?? {}).length} {t('db_tables')}{/if}
									</div>
								</div>
								<div class="flex items-center gap-x-1.5">
									<Button variant="ghost" size="sm" class="h-7 px-2 text-xs gap-x-1"
										disabled={discoveringId === db.id}
										onclick={(e) => { e.stopPropagation(); discoverSchema(db.id); }}>
										{#if discoveringId === db.id}
											<Loader2 class="w-3 h-3 animate-spin" />
										{:else}
											<RefreshCcw class="w-3 h-3" />
										{/if}
										{t('db_discover')}
									</Button>
									<Button variant="ghost" size="sm" class="h-7 px-2 text-destructive hover:text-destructive text-xs"
										onclick={(e) => { e.stopPropagation(); deleteDatabase(db.id); }}>
										<Trash2 class="w-3 h-3" />
									</Button>
								</div>
							</div>

							<!-- Schema browser & annotations -->
							{#if selectedDB?.id === db.id && selectedDB.schema}
								<div class="border-t px-4 py-4 space-y-4">
									<p class="text-xs text-muted-foreground">Tablo ve kolon açıklamalarını düzenleyin. Bu açıklamalar ajan SQL üretirken kullanılır.</p>
									{#each Object.entries(selectedDB.schema.tables ?? {}) as [tname, tdata]}
										<div class="space-y-2">
											<div class="flex items-start gap-x-2">
												<Table2 class="w-3.5 h-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
												<div class="flex-1 space-y-1.5">
													<div class="flex items-center gap-x-2">
														<span class="font-mono text-xs font-semibold">{tname}</span>
														<span class="text-xs text-muted-foreground">{tdata.row_count.toLocaleString()} {t('db_table_rows')}</span>
													</div>
													<input type="text" bind:value={tdata.description}
														placeholder={t('db_schema_desc')}
														class="w-full h-8 px-2.5 text-xs rounded-lg border border-input bg-muted/40 focus:outline-none focus:ring-1 focus:ring-ring" />
													<div class="pl-3 border-l border-border/50 space-y-1.5">
														{#each Object.entries(tdata.columns) as [cname, cdata]}
															<div class="flex items-center gap-x-2">
																<Code2 class="w-3 h-3 text-muted-foreground/50 flex-shrink-0" />
																<span class="font-mono text-xs text-muted-foreground w-32 flex-shrink-0 truncate">{cname}</span>
																<span class="text-xs text-muted-foreground/60 w-20 flex-shrink-0 truncate">{cdata.type}</span>
																{#if cdata.primary_key}<span class="text-xs text-amber-600">PK</span>{/if}
																{#if cdata.foreign_key}<span class="text-xs text-blue-500 truncate max-w-20" title={cdata.foreign_key}>→{cdata.foreign_key}</span>{/if}
																<input type="text" bind:value={cdata.description}
																	placeholder="Açıklama..."
																	class="flex-1 h-7 px-2 text-xs rounded border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
															</div>
														{/each}
													</div>
												</div>
											</div>
										</div>
									{/each}

									<!-- Example queries -->
									<div class="space-y-2">
										<p class="text-xs font-medium text-muted-foreground">{t('db_examples_title')}
											<span class="font-normal">{t('db_examples_hint')}</span>
										</p>
										{#each (selectedDB.examples ?? []) as ex, i}
											<div class="space-y-1">
												<input type="text" bind:value={ex.description} placeholder="Açıklama..."
													class="w-full h-7 px-2.5 text-xs rounded border border-input bg-background focus:outline-none" />
												<textarea bind:value={ex.sql} rows="2"
													class="w-full px-2.5 py-1.5 text-xs font-mono rounded border border-input bg-muted/40 focus:outline-none resize-none"></textarea>
											</div>
										{/each}
										<Button variant="ghost" size="sm" class="h-7 px-2 text-xs"
											onclick={() => { if (selectedDB) selectedDB.examples = [...(selectedDB.examples ?? []), { sql: '', description: '' }]; }}>
											<Plus class="w-3 h-3 mr-1" /> {t('db_examples_add')}
										</Button>
									</div>

									<Button variant="default" size="sm" class="h-8 px-4 text-xs" onclick={saveAnnotations}>
										{t('db_save_annotations')}
									</Button>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	<!-- ── ENTEGRASYONLAR TAB ───────────────────────────────────────────── -->
	{#if tab === 'social'}
		<div class="space-y-8">

		<!-- ── Telegram ──────────────────────────────────────────────────────── -->
		<div>
			<h3 class="text-sm font-semibold mb-3 flex items-center gap-x-2">
				<MessageSquare class="w-4 h-4 text-sky-500" />
				Telegram Bildirimleri
			</h3>
			<p class="text-xs text-muted-foreground mb-4">
				BotFather ile oluşturduğunuz bot token ve admin chat ID'yi girerek
				davet, şifre sıfırlama ve ajan bildirimlerini Telegram'dan alın.
			</p>

			{#if tgError}
				<div class="mb-3 flex items-center gap-x-2 text-sm text-destructive bg-destructive/10 px-4 py-3 rounded-xl">
					<XCircle class="w-4 h-4 flex-shrink-0" />{tgError}
				</div>
			{/if}
			{#if tgSuccess}
				<div class="mb-3 flex items-center gap-x-2 text-sm text-emerald-700 bg-emerald-50 px-4 py-3 rounded-xl">
					<CheckCircle2 class="w-4 h-4 flex-shrink-0" />{tgSuccess}
				</div>
			{/if}

			{#if tgLoading}
				<div class="flex justify-center py-8"><Loader2 class="w-5 h-5 animate-spin text-muted-foreground" /></div>
			{:else if tgConfig?.configured && !tgEditMode}
				<!-- Configured card -->
				<div class="rounded-2xl border border-sky-500/30 bg-card">
					<div class="flex items-center justify-between px-5 py-4">
						<div class="flex items-center gap-x-3">
							<CheckCircle2 class="w-5 h-5 text-sky-500 flex-shrink-0" />
							<div>
								<div class="font-semibold text-sm">{t('tg_connected')}</div>
								<div class="text-xs text-muted-foreground mt-0.5">
									Chat ID: <code class="font-mono">{tgConfig.admin_chat_id}</code>
								</div>
							</div>
						</div>
						<div class="flex items-center gap-x-2">
							<Button variant="ghost" size="sm" class="h-8 px-3 text-xs gap-x-1.5"
								disabled={tgTesting} onclick={testTelegram}>
								{#if tgTesting}<Loader2 class="w-3.5 h-3.5 animate-spin" />{:else}<RefreshCw class="w-3.5 h-3.5" />{/if}
								Test
							</Button>
							<Button variant="ghost" size="sm" class="h-8 px-3 text-xs"
								onclick={() => { tgEditMode = true; }}>
								{t('tg_update')}
							</Button>
							<Button variant="ghost" size="sm" class="h-8 px-3 text-xs text-destructive hover:text-destructive gap-x-1.5"
								disabled={tgDeleting} onclick={deleteTelegram}>
								{#if tgDeleting}<Loader2 class="w-3.5 h-3.5 animate-spin" />{:else}<Trash2 class="w-3.5 h-3.5" />{/if}
								{t('tg_remove')}
							</Button>
						</div>
					</div>
				</div>
			{:else}
				<!-- Configure form -->
				<div class="rounded-2xl border bg-card p-5 space-y-4">
					<div class="grid grid-cols-2 gap-4">
						<div>
							<label class="block text-xs font-medium text-muted-foreground mb-1.5">
								Bot Token <span class="text-destructive">*</span>
							</label>
							<div class="relative">
								<input type={tgShowToken ? 'text' : 'password'}
									bind:value={tgForm.bot_token}
									placeholder="123456789:AAF..."
									class="w-full h-9 px-3 pr-10 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
								<button class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
									onclick={() => (tgShowToken = !tgShowToken)} type="button" tabindex="-1">
									{#if tgShowToken}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
								</button>
							</div>
							<p class="mt-1 text-xs text-muted-foreground">BotFather → /newbot → token</p>
						</div>
						<div>
							<label class="block text-xs font-medium text-muted-foreground mb-1.5">
								Admin Chat ID <span class="text-destructive">*</span>
							</label>
							<input type="text" bind:value={tgForm.admin_chat_id}
								placeholder="-100123456789"
								class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring"
								onkeydown={(e) => e.key === 'Enter' && saveTelegram()} />
							<p class="mt-1 text-xs text-muted-foreground">@userinfobot veya grup ID'si</p>
						</div>
					</div>
					<div class="flex justify-end gap-x-2">
						{#if tgEditMode}
							<Button variant="ghost" size="sm" class="h-8 px-3 text-xs"
								onclick={() => { tgEditMode = false; tgError = ''; }}>{t('cancel')}</Button>
						{/if}
						<Button variant="default" size="sm" class="h-8 px-4 text-xs"
							disabled={tgSaving || !tgForm.bot_token.trim() || !tgForm.admin_chat_id.trim()}
							onclick={saveTelegram}>
							{#if tgSaving}<Loader2 class="w-3.5 h-3.5 animate-spin mr-1.5" />{t('tg_verify')}{:else}{t('settings_connect_btn')}{/if}
						</Button>
					</div>
				</div>
			{/if}
		</div>

		<div class="border-t border-border/50"></div>

		<!-- ── Sosyal Medya ───────────────────────────────────────────────────── -->
		<div>
			<h3 class="text-sm font-semibold mb-3 flex items-center gap-x-2">
				<Share2 class="w-4 h-4 text-pink-500" />
				{t('social_tab_title')}
			</h3>
			<p class="text-xs text-muted-foreground mb-4">
				Instagram Business ve WhatsApp Business Cloud API entegrasyonu. Ajanlara
				<code class="text-xs bg-muted px-1 py-0.5 rounded">instagram_post</code> ve
				<code class="text-xs bg-muted px-1 py-0.5 rounded">whatsapp_send</code> skill'leri
				ekleyerek sosyal medya paylaşımı yapabilirler.
			</p>

			{#if socialError}
				<div class="flex items-center gap-x-2 text-sm text-destructive bg-destructive/10 px-4 py-3 rounded-xl">
					<XCircle class="w-4 h-4 flex-shrink-0" />
					{socialError}
				</div>
			{/if}
			{#if socialSuccess}
				<div class="flex items-center gap-x-2 text-sm text-emerald-700 bg-emerald-50 px-4 py-3 rounded-xl">
					<CheckCircle2 class="w-4 h-4 flex-shrink-0" />
					{socialSuccess}
				</div>
			{/if}

			{#if socialLoading}
				<div class="flex justify-center py-12">
					<Loader2 class="w-5 h-5 animate-spin text-muted-foreground" />
				</div>
			{:else}
				<!-- Instagram -->
				<div class="rounded-2xl border bg-card overflow-hidden">
					<div class="flex items-center gap-x-3 px-5 py-4 border-b border-border/50">
						<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 via-pink-500 to-orange-400 flex items-center justify-center flex-shrink-0">
							<Share2 class="w-4 h-4 text-white" />
						</div>
						<div class="flex-1 min-w-0">
							<div class="font-semibold text-sm flex items-center gap-x-2">
								Instagram Business
								{#if socialConfig?.instagram_configured}
									<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-700">{t('social_active')}</span>
								{:else}
									<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground">{t('social_unconfigured')}</span>
								{/if}
							</div>
							<div class="text-xs text-muted-foreground mt-0.5">
								{#if socialConfig?.ig_user_id}
									IG User ID: {socialConfig.ig_user_id}
								{:else}
									Meta Graph API v21.0 · Graph API Explorer'dan token alın
								{/if}
							</div>
						</div>
					</div>
					<div class="px-5 py-4 space-y-3">
						<div class="grid grid-cols-2 gap-3">
							<div>
								<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="ig-user-id">
									IG Business User ID <span class="text-destructive">*</span>
								</label>
								<input id="ig-user-id" type="text" bind:value={socialForm.ig_user_id}
									placeholder="17841400000000000"
									class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
							</div>
							<div>
								<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="ig-token">
									Access Token <span class="text-destructive">*</span>
									{#if socialConfig?.instagram_configured && !socialForm.ig_access_token}
										<span class="font-normal text-muted-foreground/70">(kayıtlı — değiştirmek için girin)</span>
									{/if}
								</label>
								<div class="relative">
									<input id="ig-token" type={showIgToken ? 'text' : 'password'}
										bind:value={socialForm.ig_access_token}
										placeholder={socialConfig?.instagram_configured ? '••••••••' : 'EAAxxxxxx...'}
										class="w-full h-9 px-3 pr-10 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
									<button type="button"
										class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
										onclick={() => (showIgToken = !showIgToken)}>
										{#if showIgToken}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
									</button>
								</div>
							</div>
						</div>
						<p class="text-xs text-muted-foreground">
							Gereken izinler: <code class="bg-muted px-1 rounded">instagram_basic</code>
							<code class="bg-muted px-1 rounded">instagram_content_publish</code>.
							Token süresiz olması için <strong>Page Access Token</strong> kullanın.
						</p>
					</div>
				</div>

				<!-- WhatsApp -->
				<div class="rounded-2xl border bg-card overflow-hidden">
					<div class="flex items-center gap-x-3 px-5 py-4 border-b border-border/50">
						<div class="w-8 h-8 rounded-lg bg-emerald-500 flex items-center justify-center flex-shrink-0">
							<MessageSquare class="w-4 h-4 text-white" />
						</div>
						<div class="flex-1 min-w-0">
							<div class="font-semibold text-sm flex items-center gap-x-2">
								WhatsApp Business
								{#if socialConfig?.whatsapp_configured}
									<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-700">{t('social_active')}</span>
								{:else}
									<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground">{t('social_unconfigured')}</span>
								{/if}
							</div>
							<div class="text-xs text-muted-foreground mt-0.5">
								{#if socialConfig?.wa_phone_number_id}
									Phone Number ID: {socialConfig.wa_phone_number_id}
								{:else}
									Meta Cloud API · İş mesajlaşması
								{/if}
							</div>
						</div>
					</div>
					<div class="px-5 py-4 space-y-3">
						<div class="grid grid-cols-2 gap-3">
							<div>
								<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="wa-phone-id">
									Phone Number ID <span class="text-destructive">*</span>
								</label>
								<input id="wa-phone-id" type="text" bind:value={socialForm.wa_phone_number_id}
									placeholder="102290000000000"
									class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
							</div>
							<div>
								<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="wa-default-to">
									Varsayılan Alıcı
								</label>
								<input id="wa-default-to" type="tel" bind:value={socialForm.wa_default_to}
									placeholder="+905551234567"
									class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
							</div>
						</div>
						<div>
							<label class="block text-xs font-medium text-muted-foreground mb-1.5" for="wa-token">
								System User Access Token <span class="text-destructive">*</span>
								{#if socialConfig?.whatsapp_configured && !socialForm.wa_access_token}
									<span class="font-normal text-muted-foreground/70">(kayıtlı — değiştirmek için girin)</span>
								{/if}
							</label>
							<div class="relative">
								<input id="wa-token" type={showWaToken ? 'text' : 'password'}
									bind:value={socialForm.wa_access_token}
									placeholder={socialConfig?.whatsapp_configured ? '••••••••' : 'EAAxxxxxx...'}
									class="w-full h-9 px-3 pr-10 text-sm rounded-lg border border-input bg-background font-mono focus:outline-none focus:ring-2 focus:ring-ring" />
								<button type="button"
									class="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
									onclick={() => (showWaToken = !showWaToken)}>
									{#if showWaToken}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
								</button>
							</div>
						</div>
						<p class="text-xs text-muted-foreground">
							Not: WhatsApp Status (Durum) hikâyeleri resmi Cloud API'de mevcut değil.
							Bu entegrasyon belirtilen numaraya <strong>metin mesajı</strong> gönderir.
						</p>
					</div>
				</div>

				<!-- Actions -->
				<div class="flex items-center justify-between">
					<Button variant="ghost" size="sm" class="h-8 px-3 text-xs text-destructive hover:text-destructive"
						onclick={deleteSocial}>
						<Trash2 class="w-3.5 h-3.5 mr-1.5" />
						{t('social_delete_all')}
					</Button>
					<Button variant="default" size="sm" class="h-8 px-5 text-xs"
						disabled={socialSaving}
						onclick={saveSocial}>
						{#if socialSaving}
							<Loader2 class="w-3.5 h-3.5 animate-spin mr-1.5" />
						{/if}
						{t('save')}
					</Button>
				</div>

				<!-- Skill guide -->
				<div class="rounded-xl border border-dashed bg-muted/30 p-4 space-y-2">
					<p class="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{t('social_skill_guide')}</p>
					<p class="text-xs text-muted-foreground">
						{t('social_skill_guide_desc')}
					</p>
					<ul class="text-xs text-muted-foreground space-y-1 list-disc pl-4">
						<li><code class="bg-background border rounded px-1">instagram_post</code> — Skill türü: <strong>builtin</strong>, parametreler: image_url, caption</li>
						<li><code class="bg-background border rounded px-1">whatsapp_send</code> — Skill türü: <strong>builtin</strong>, parametreler: message, to (opsiyonel)</li>
					</ul>
				</div>
			{/if}
		</div>
		</div>
	{/if}

	<!-- ── AUDIT LOG TAB ─────────────────────────────────────────────────── -->
	{#if tab === 'audit'}
	<div class="space-y-4">
		<div class="flex items-center gap-3">
			<select
				bind:value={auditEntityFilter}
				onchange={loadAuditLogs}
				class="h-9 rounded-md border border-border bg-background px-3 py-1 text-sm"
			>
				<option value="">All types</option>
				<option value="department">Departments</option>
				<option value="personnel">Personnel</option>
				<option value="agent_config">Agent Config</option>
				<option value="skill">Skills</option>
				<option value="flow">Flows</option>
				<option value="change_request">Change Requests</option>
				<option value="provider_key">Provider Keys</option>
			</select>
			<button onclick={loadAuditLogs} class="inline-flex items-center gap-1.5 h-9 px-3 rounded-md border border-border text-sm hover:bg-muted">
				<RefreshCw class="h-3.5 w-3.5" />
				Refresh
			</button>
		</div>

		{#if auditLoading}
			<div class="flex justify-center py-8">
				<Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
			</div>
		{:else if auditLogs.length === 0}
			<div class="text-center py-8 text-muted-foreground text-sm">No audit logs found.</div>
		{:else}
			<div class="rounded-md border border-border overflow-hidden">
				<table class="w-full text-sm">
					<thead class="bg-muted/50">
						<tr>
							<th class="text-left px-4 py-2.5 font-medium text-muted-foreground">Time</th>
							<th class="text-left px-4 py-2.5 font-medium text-muted-foreground">Action</th>
							<th class="text-left px-4 py-2.5 font-medium text-muted-foreground">Type</th>
							<th class="text-left px-4 py-2.5 font-medium text-muted-foreground">Entity</th>
						</tr>
					</thead>
					<tbody>
						{#each auditLogs as log}
							<tr class="border-t border-border hover:bg-muted/30">
								<td class="px-4 py-2.5 text-muted-foreground whitespace-nowrap">
									{new Date(log.created_at).toLocaleString()}
								</td>
								<td class="px-4 py-2.5">
									<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium
										{log.action === 'create' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' :
										 log.action === 'delete' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' :
										 log.action === 'approve' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' :
										 log.action === 'reject' ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400' :
										 'bg-muted text-muted-foreground'}">
										{log.action}
									</span>
								</td>
								<td class="px-4 py-2.5 text-muted-foreground">{log.entity_type}</td>
								<td class="px-4 py-2.5 font-medium">{log.entity_name || log.entity_id || '—'}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
	{/if}
</div>


<style>
.tab-scroll {
	overflow-x: auto;
	scrollbar-width: none;
	-ms-overflow-style: none;
}
.tab-scroll::-webkit-scrollbar { display: none; }

.tab-btn {
	position: relative;
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding: 0.625rem 1rem;
	font-size: 0.875rem;
	font-weight: 500;
	white-space: nowrap;
	flex-shrink: 0;
	transition: color 0.15s;
	border: none;
	background: transparent;
	cursor: pointer;
}
.tab-btn::after {
	content: '';
	position: absolute;
	bottom: 0; left: 0; right: 0;
	height: 2px;
	border-radius: 9999px;
	transition: background 0.15s;
}
.tab-active { color: hsl(var(--foreground)); }
.tab-active::after { background: hsl(var(--primary)); }
.tab-inactive { color: hsl(var(--muted-foreground)); }
.tab-inactive:hover { color: hsl(var(--foreground)); }
.tab-inactive::after { background: transparent; }
</style>
