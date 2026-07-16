<script lang="ts">
	import { onMount } from 'svelte';
	import { inbox as inboxApi, taskRequests as taskApi, type InboxMessage, type TaskRequest } from '$lib/api/inbox';
	import { API_URL } from '$lib/api/client';
	import { companyStore } from '$lib/stores/company.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { departments as deptApi, type Department } from '$lib/api/departments';
	import Button from '$lib/components/ui/button.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import {
		Inbox, Mail, MailOpen, Trash2, CheckCheck, Loader, AlertCircle,
		Plus, X, Zap, FileText, Bot, CheckCircle2
	} from '@lucide/svelte';
	import { t } from '$lib/i18n/index.svelte';

	const activeCompanyId = $derived(companyStore.active?.id ?? '');

	// ── Inbox messages ────────────────────────────────────────────────────────
	let messages: InboxMessage[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);
	let period = $state('');          // '' | 'week' | 'month'
	let unreadOnly = $state(false);
	let expandedMsgId: string | null = $state(null);

	async function loadMessages() {
		if (!activeCompanyId) return;
		loading = true; error = null;
		try {
			messages = await inboxApi.list({ company_id: activeCompanyId, unread_only: unreadOnly || undefined, period: period || undefined });
		} catch (e) { error = (e as Error).message; }
		finally { loading = false; }
	}

	async function markRead(msg: InboxMessage) {
		if (msg.read) return;
		const updated = await inboxApi.markRead(msg.id);
		messages = messages.map(m => m.id === msg.id ? updated : m);
	}

	async function markAllRead() {
		await inboxApi.markAllRead(activeCompanyId);
		messages = messages.map(m => ({ ...m, read: true }));
	}

	async function deleteMsg(id: string) {
		await inboxApi.delete(id);
		messages = messages.filter(m => m.id !== id);
	}

	const unreadCount = $derived(messages.filter(m => !m.read).length);

	function sourceIcon(t: InboxMessage['source_type']) {
		return { flow: Zap, task_request: FileText, task_result: Bot, system: Inbox }[t] ?? Inbox;
	}

	function sourceLabel(t: InboxMessage['source_type']) {
		return { flow: 'Akış', task_request: 'Görev', task_result: 'Sonuç', system: 'Sistem' }[t] ?? t;
	}

	// ── New Task Request form ─────────────────────────────────────────────────
	let showTaskForm = $state(false);
	let departments: Department[] = $state([]);
	let taskForm = $state({ department_id: '', skill_filter: '', title: '', body: '' });
	let taskSaving = $state(false);

	async function loadDepts() {
		if (!activeCompanyId) return;
		departments = await deptApi.list(activeCompanyId);
	}

	async function submitTask() {
		if (!taskForm.title || !taskForm.body) return;
		taskSaving = true;
		try {
			await taskApi.create({
				company_id: activeCompanyId,
				department_id: taskForm.department_id || undefined,
				skill_filter: taskForm.skill_filter || undefined,
				title: taskForm.title,
				body: taskForm.body,
			});
			taskForm = { department_id: '', skill_filter: '', title: '', body: '' };
			showTaskForm = false;
			loadMessages();
		} catch (e) { alert((e as Error).message); }
		finally { taskSaving = false; }
	}

	// ── Tasks assigned to me ──────────────────────────────────────────────────
	let myTasks: TaskRequest[] = $state([]);
	let taskNote: Record<string, string> = $state({});
	let taskActioning: string | null = $state(null);

	// ── Streaming state ───────────────────────────────────────────────────────
	let streamingTaskId: string | null = $state(null);
	let streamSteps: Array<{ step: string; label: string }> = $state([]);
	let streamOutput: string = $state('');
	let streamStatus: 'running' | 'done' | 'error' = $state('running');
	let streamErrorMsg: string = $state('');

	async function loadMyTasks() {
		if (!activeCompanyId) return;
		myTasks = await taskApi.list({ company_id: activeCompanyId });
	}

	async function runTask(task: TaskRequest) {
		taskActioning = task.id;
		streamingTaskId = task.id;
		streamSteps = [];
		streamOutput = '';
		streamStatus = 'running';
		streamErrorMsg = '';

		try {
			const token = typeof localStorage !== 'undefined' ? localStorage.getItem('auth_token') : null;

			// Open SSE connection before firing run so the queue is registered first
			const resp = await fetch(`${API_URL}/task-requests/${task.id}/stream`, {
				headers: token ? { 'Authorization': `Bearer ${token}` } : {}
			});
			if (!resp.ok) throw new Error(`Akış bağlantısı hatası: ${resp.status}`);

			// Fire run non-blocking — it will emit to the queue we just registered
			taskApi.run(task.id, taskNote[task.id] || undefined)
				.then(updated => {
					myTasks = myTasks.map(t => t.id === task.id ? updated : t);
					loadMessages();
				})
				.catch(e => {
					if (streamStatus === 'running') {
						streamStatus = 'error';
						streamErrorMsg = (e as Error).message;
					}
				});

			taskActioning = null;

			// Drain SSE stream
			const reader = resp.body!.getReader();
			const decoder = new TextDecoder();
			let buffer = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;
				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() ?? '';

				for (const line of lines) {
					if (!line.startsWith('data:')) continue;
					try {
						const data = JSON.parse(line.slice(5).trim());
						if (data.type === 'step') {
							streamSteps = [...streamSteps, { step: data.step, label: data.label }];
						} else if (data.type === 'chunk') {
							streamOutput += data.text;
						} else if (data.type === 'done') {
							streamStatus = 'done';
						} else if (data.type === 'error') {
							streamStatus = 'error';
							streamErrorMsg = data.message;
						}
					} catch { /* skip malformed SSE line */ }
				}
				if (streamStatus !== 'running') break;
			}
		} catch (e) {
			streamStatus = 'error';
			streamErrorMsg = (e as Error).message;
			taskActioning = null;
		}
	}

	async function rejectTask(task: TaskRequest) {
		taskActioning = task.id;
		try {
			const updated = await taskApi.reject(task.id, taskNote[task.id] || undefined);
			myTasks = myTasks.map(t => t.id === task.id ? updated : t);
		} catch (e) { alert((e as Error).message); }
		finally { taskActioning = null; }
	}

	function relTime(iso: string) {
		const diff = Date.now() - new Date(iso).getTime();
		const m = Math.floor(diff / 60000);
		if (m < 1) return 'az önce';
		if (m < 60) return `${m}dk`;
		const h = Math.floor(m / 60);
		if (h < 24) return `${h}sa`;
		return `${Math.floor(h / 24)}g`;
	}

	onMount(() => { loadMessages(); loadMyTasks(); loadDepts(); });
	$effect(() => { if (companyStore.active) { loadMessages(); loadMyTasks(); loadDepts(); } });
	$effect(() => { loadMessages(); });  // period/unreadOnly reactive

	// Poll every 30 seconds
	onMount(() => {
		const t = setInterval(() => { loadMessages(); loadMyTasks(); }, 30000);
		return () => clearInterval(t);
	});
</script>

<svelte:head><title>Gelen Kutusu • fab.engineering</title></svelte:head>

<div class="space-y-6 max-w-4xl">
	<!-- Header -->
	<div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
		<div class="flex items-center gap-3">
			<h1 class="font-display text-3xl tracking-tight">{t('inbox_title')}</h1>
			{#if unreadCount > 0}
				<Badge variant="default" class="text-xs">{unreadCount} {t('inbox_new_badge')}</Badge>
			{/if}
		</div>
		<div class="flex gap-2">
			{#if unreadCount > 0}
				<Button variant="outline" size="sm" onclick={markAllRead}>
					<CheckCheck class="w-4 h-4" /> {t('inbox_mark_all_read')}
				</Button>
			{/if}
			<Button size="sm" onclick={() => { showTaskForm = !showTaskForm; }}>
				<Plus class="w-4 h-4" /> {t('inbox_new_task')}
			</Button>
		</div>
	</div>

	<!-- New Task Form -->
	{#if showTaskForm}
		<div class="rounded-xl border bg-card p-5 space-y-4">
			<div class="flex items-center justify-between">
				<h3 class="font-semibold text-sm">{t('inbox_new_task_title')}</h3>
				<button onclick={() => (showTaskForm = false)} class="text-muted-foreground hover:text-foreground">
					<X class="w-4 h-4" />
				</button>
			</div>
			<div class="grid sm:grid-cols-2 gap-3">
				<div class="space-y-1">
					<label class="text-xs font-medium text-muted-foreground">{t('inbox_dept_label')}</label>
					<select bind:value={taskForm.department_id} class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring">
						<option value="">{t('inbox_dept_all')}</option>
						{#each departments as d (d.id)}
							<option value={d.id}>{d.name}</option>
						{/each}
					</select>
				</div>
				<div class="space-y-1">
					<label class="text-xs font-medium text-muted-foreground">{t('inbox_skill_filter_label')}</label>
					<input bind:value={taskForm.skill_filter} placeholder={t('inbox_skill_filter_ph')} class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
				</div>
			</div>
			<div class="space-y-1">
				<label class="text-xs font-medium text-muted-foreground">{t('inbox_task_title_label')}</label>
				<input bind:value={taskForm.title} placeholder={t('inbox_task_title_ph')} class="w-full h-9 px-3 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring" />
			</div>
			<div class="space-y-1">
				<label class="text-xs font-medium text-muted-foreground">{t('inbox_task_body_label')}</label>
				<textarea bind:value={taskForm.body} rows={3} placeholder={t('inbox_task_body_ph')} class="w-full px-3 py-2 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-none"></textarea>
			</div>
			<div class="flex justify-end gap-2">
				<Button variant="outline" size="sm" onclick={() => (showTaskForm = false)}>{t('cancel')}</Button>
				<Button size="sm" onclick={submitTask} disabled={taskSaving || !taskForm.title || !taskForm.body}>
					{taskSaving ? t('sending') : t('inbox_task_send')}
				</Button>
			</div>
		</div>
	{/if}

	<!-- Pending / running tasks assigned to me -->
	{#if myTasks.filter(task => (task.status === 'assigned' || task.status === 'running') && task.responsible_user_id === authStore.user?.id).length > 0}
		<div class="space-y-2">
			<h3 class="text-sm font-semibold text-muted-foreground uppercase tracking-wide">{t('inbox_pending_tasks')}</h3>
			{#each myTasks.filter(task => (task.status === 'assigned' || task.status === 'running') && task.responsible_user_id === authStore.user?.id) as task (task.id)}
				<div class="rounded-xl border bg-amber-50/50 dark:bg-amber-950/20 border-amber-200/60 p-4 space-y-3">
					<div class="flex items-start justify-between gap-2">
						<div>
							<div class="font-medium text-sm">{task.title}</div>
							<div class="text-xs text-muted-foreground mt-0.5">{task.body}</div>
						</div>
						<span class="text-xs text-muted-foreground flex-shrink-0">{relTime(task.created_at)}</span>
					</div>

					{#if streamingTaskId === task.id}
						<!-- Live streaming panel -->
						<div class="rounded-lg border bg-card p-3 space-y-2">
							<div class="flex flex-wrap gap-1.5">
								{#each streamSteps as s}
									<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
										<CheckCircle2 class="w-3 h-3" /> {s.label}
									</span>
								{/each}
								{#if streamStatus === 'running'}
									<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground">
										<Loader class="w-3 h-3 animate-spin" /> Çalışıyor...
									</span>
								{/if}
							</div>

							{#if streamOutput}
								<div class="rounded bg-muted/50 p-2.5 max-h-52 overflow-y-auto">
									<pre class="text-xs whitespace-pre-wrap font-sans leading-relaxed">{streamOutput}</pre>{#if streamStatus === 'running'}<span class="inline-block w-0.5 h-3 bg-foreground/60 animate-pulse ml-px"></span>{/if}
								</div>
							{/if}

							{#if streamStatus === 'error'}
								<p class="text-xs text-destructive flex items-center gap-1">
									<AlertCircle class="w-3 h-3" /> {streamErrorMsg}
								</p>
							{/if}

							{#if streamStatus === 'done'}
								<div class="flex items-center justify-between">
									<p class="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
										<CheckCircle2 class="w-3 h-3" /> Görev tamamlandı — sonuç gelen kutusuna iletildi
									</p>
									<Button size="sm" variant="outline" onclick={() => { streamingTaskId = null; }}>
										<X class="w-3 h-3" /> Kapat
									</Button>
								</div>
							{/if}
						</div>
					{:else}
						<textarea
							bind:value={taskNote[task.id]}
							placeholder={t('inbox_task_note_ph')}
							rows={2}
							class="w-full px-3 py-2 text-sm rounded-lg border border-input bg-background focus:outline-none focus:ring-1 focus:ring-ring resize-none"
						></textarea>
						<div class="flex gap-2">
							<Button size="sm" onclick={() => runTask(task)} disabled={taskActioning === task.id || task.status === 'running'}>
								<Bot class="w-3.5 h-3.5" />
								{taskActioning === task.id ? t('running') : t('inbox_task_run')}
							</Button>
							<Button size="sm" variant="outline" onclick={() => rejectTask(task)} disabled={taskActioning === task.id || task.status === 'running'}>{t('inbox_task_reject')}</Button>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	<!-- Filters -->
	<div class="flex flex-wrap items-center gap-2">
		<div class="flex gap-1">
			{#each [{ v: '', l: t('inbox_filter_all') }, { v: 'week', l: t('inbox_filter_week') }, { v: 'month', l: t('inbox_filter_month') }] as f}
				<button
					onclick={() => { period = f.v; }}
					class={['px-3 py-1.5 rounded-lg text-sm font-medium transition-colors', period === f.v ? 'bg-primary text-primary-foreground' : 'bg-muted/60 text-muted-foreground hover:text-foreground'].join(' ')}
				>
					{f.l}
				</button>
			{/each}
		</div>
		<button
			onclick={() => { unreadOnly = !unreadOnly; }}
			class={['px-3 py-1.5 rounded-lg text-sm font-medium transition-colors', unreadOnly ? 'bg-primary text-primary-foreground' : 'bg-muted/60 text-muted-foreground hover:text-foreground'].join(' ')}
		>
			{t('inbox_unread_only')}
		</button>
	</div>

	<!-- Message list -->
	{#if loading}
		<div class="flex items-center justify-center py-20 text-muted-foreground gap-2">
			<Loader class="w-4 h-4 animate-spin" />
			<span class="text-sm">{t('loading')}</span>
		</div>
	{:else if error}
		<div class="flex items-center gap-2 text-sm text-destructive bg-destructive/10 rounded-xl border border-destructive/30 px-4 py-3">
			<AlertCircle class="w-4 h-4" /> {error}
		</div>
	{:else if messages.length === 0}
		<div class="rounded-xl border bg-card flex flex-col items-center justify-center py-20 gap-3">
			<div class="w-12 h-12 rounded-xl bg-muted flex items-center justify-center">
				<Inbox class="w-6 h-6 text-muted-foreground" />
			</div>
			<p class="font-medium">{t('inbox_empty')}</p>
			<p class="text-sm text-muted-foreground">{t('inbox_empty_subtitle')}</p>
		</div>
	{:else}
		<div class="space-y-2">
			{#each messages as msg (msg.id)}
				{@const expanded = expandedMsgId === msg.id}
				{@const Icon = sourceIcon(msg.source_type)}
				<div
					class={['rounded-xl border bg-card overflow-hidden transition-all', !msg.read ? 'border-primary/30' : ''].join(' ')}
				>
					<!-- Row: click area + delete action side by side -->
					<div class="flex items-start">
						<!-- svelte-ignore a11y_interactive_supports_focus -->
						<div
							role="button"
							tabindex="0"
							class="flex-1 flex items-start gap-3 px-4 py-3.5 text-left hover:bg-muted/20 transition-colors cursor-pointer"
							onclick={() => { expandedMsgId = expanded ? null : msg.id; markRead(msg); }}
							onkeydown={(e) => { if (e.key === 'Enter') { expandedMsgId = expanded ? null : msg.id; markRead(msg); } }}
						>
							<div class={['w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5', msg.source_type === 'flow' ? 'bg-violet-100' : msg.source_type === 'task_result' ? 'bg-emerald-100' : 'bg-blue-100'].join(' ')}>
								<Icon class={['w-4 h-4', msg.source_type === 'flow' ? 'text-violet-600' : msg.source_type === 'task_result' ? 'text-emerald-600' : 'text-blue-600'].join(' ')} />
							</div>
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2">
									{#if !msg.read}
										<div class="w-2 h-2 rounded-full bg-primary flex-shrink-0"></div>
									{/if}
									<span class={['text-sm truncate', !msg.read ? 'font-semibold' : 'font-medium'].join(' ')}>{msg.title}</span>
									<Badge variant="outline" class="text-xs flex-shrink-0">{sourceLabel(msg.source_type)}</Badge>
								</div>
								{#if !expanded}
									<p class="text-xs text-muted-foreground mt-0.5 truncate">{msg.body.slice(0, 80)}</p>
								{/if}
							</div>
							<span class="text-xs text-muted-foreground flex-shrink-0 mt-0.5">{relTime(msg.created_at)}</span>
						</div>
						<button
							onclick={() => deleteMsg(msg.id)}
							class="px-3 py-3.5 text-muted-foreground hover:text-destructive transition-colors flex-shrink-0"
							aria-label={t('delete')}
						>
							<Trash2 class="w-3.5 h-3.5" />
						</button>
					</div>
					{#if expanded}
						<div class="border-t px-4 py-4 bg-muted/10">
							<pre class="text-sm whitespace-pre-wrap font-sans leading-relaxed">{msg.body}</pre>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
