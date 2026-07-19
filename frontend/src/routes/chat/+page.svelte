<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { page } from '$app/stores';
	import {
		Bot,
		Send,
		Plus,
		ChevronDown,
		Loader2,
		Wrench,
		CheckCircle2,
		X,
		MessageSquare,
		Shield,
		Zap,
		Info,
		Paperclip,
		FileText,
		Image,
		RefreshCw,
		AlertTriangle,
	} from '@lucide/svelte';
	import Button from '$lib/components/ui/button.svelte';
	import MessageContent from '$lib/components/MessageContent.svelte';
	import {
		sessionsApi,
		streamMessage,
		type Session,
		type SessionMessage,
		type Attachment,
	} from '$lib/api/sessions';
	import { personnel as personnelApi, type PersonnelItem } from '$lib/api/personnel';
	import { providers as providersApi, type ProviderStatus } from '$lib/api/providers';
	import { companyStore } from '$lib/stores/company.svelte';
	import { t } from '$lib/i18n/index.svelte';

	const LAST_SESSION_KEY = 'chat:lastSessionId';
	const POLL_INTERVAL_MS = 3000;

	function uuid(): string {
		if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
		return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
			const r = Math.random() * 16 | 0;
			return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
		});
	}

	function detectProvider(model: string): string {
		if (model.startsWith('claude')) return 'anthropic';
		if (model.startsWith('gpt') || model.startsWith('o1') || model.startsWith('o3')) return 'openai';
		if (model.startsWith('gemini')) return 'google';
		if (model.startsWith('qwen')) return 'qwen';
		return 'unknown';
	}

	function agentHasKey(agent: PersonnelItem): boolean {
		const model = agent.agent_config?.model;
		if (!model) return true;
		const provider = detectProvider(model);
		const ps = providerStatuses.find(p => p.provider === provider);
		return ps ? ps.status === 'active' : true; // unknown provider → assume ok
	}

	// ── State ─────────────────────────────────────────────────────────────────

	let agents = $state<PersonnelItem[]>([]);
	let sessions = $state<Session[]>([]);
	let providerStatuses = $state<ProviderStatus[]>([]);
	let activeSession = $state<Session | null>(null);
	let messages = $state<SessionMessage[]>([]);

	let selectedAgent = $state<PersonnelItem | null>(null);
	let agentMenuOpen = $state(false);
	let infoPanelOpen = $state(true);
	let agentSkills = $state<Array<{ id: string; name: string; version: string; description: string | null; skill_type: string; is_active: boolean }>>([]);

	let input = $state('');
	let streaming = $state(false);
	let streamingText = $state('');
	let streamingTools = $state<Array<{ name: string; args: unknown; result?: string }>>([]);
	let streamError = $state<string | null>(null);

	// File attachments
	let pendingAttachments = $state<Attachment[]>([]);
	let fileUploading = $state(false);
	let fileInputEl = $state<HTMLInputElement | null>(null);
	let fileUploadError = $state<string | null>(null);

	// Background-run polling
	let polling = $state(false);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	let messagesEl = $state<HTMLElement | null>(null);
	let inputEl = $state<HTMLTextAreaElement | null>(null);
	let abortController: AbortController | null = null;

	// ── Load ─────────────────────────────────────────────────────────────────

	onMount(async () => {
		await loadAgents();
		await loadSessions();
		try { providerStatuses = await providersApi.status(); } catch { /* ignore */ }

		// Pre-select agent from URL param
		const agentId = $page.url.searchParams.get('agent');
		if (agentId) {
			selectedAgent = agents.find((a) => a.id === agentId) ?? null;
		}

		// Restore last active session from localStorage
		const lastId = localStorage.getItem(LAST_SESSION_KEY);
		if (lastId && !activeSession) {
			const s = sessions.find((x) => x.id === lastId);
			if (s) await openSession(s);
		}
	});

	$effect(() => {
		if (companyStore.active) {
			stopPolling();
			activeSession = null;
			messages = [];
			selectedAgent = null;
			agentSkills = [];
			pendingAttachments = [];
			loadAgents();
			loadSessions();
		}
	});

	async function loadAgents() {
		try {
			agents = await personnelApi.list({
				type: 'agent',
				company_id: companyStore.active?.id
			});
		} catch {
			agents = [];
		}
	}

	async function loadSessions() {
		try {
			const all = await sessionsApi.list();
			const agentIds = new Set(agents.map(a => a.id));
			sessions = all.filter(s => agentIds.has(s.personnel_id));
		} catch {
			sessions = [];
		}
	}

	const visibleSessions = $derived(
		selectedAgent ? sessions.filter(s => s.personnel_id === selectedAgent!.id) : sessions
	);

	async function loadAgentInfo(agent: PersonnelItem) {
		try {
			const skills = await personnelApi.listSkills(agent.id);
			agentSkills = skills as typeof agentSkills;
		} catch {
			agentSkills = [];
		}
	}

	async function openSession(s: Session) {
		stopPolling();
		activeSession = s;
		localStorage.setItem(LAST_SESSION_KEY, s.id);
		const detail = await sessionsApi.get(s.id);
		messages = detail.messages ?? [];
		const agent = agents.find((a) => a.id === s.personnel_id) ?? null;
		selectedAgent = agent;
		if (agent) await loadAgentInfo(agent);

		// If session was running when we were away, start polling
		if (detail.status === 'running') {
			startPolling(s.id);
		}

		await scrollToBottom();
	}

	async function newSession() {
		if (!selectedAgent) return;
		const s = await sessionsApi.create(selectedAgent.id);
		sessions = [s, ...sessions];
		activeSession = s;
		messages = [];
		localStorage.setItem(LAST_SESSION_KEY, s.id);
	}

	async function closeSession(s: Session) {
		await sessionsApi.close(s.id);
		sessions = sessions.filter((x) => x.id !== s.id);
		if (activeSession?.id === s.id) {
			stopPolling();
			activeSession = null;
			messages = [];
			localStorage.removeItem(LAST_SESSION_KEY);
		}
	}

	// ── Background polling ────────────────────────────────────────────────────

	function startPolling(sessionId: string) {
		stopPolling();
		polling = true;
		pollTimer = setInterval(async () => {
			try {
				const status = await sessionsApi.getStatus(sessionId);
				messages = status.messages;
				await scrollToBottom();
				if (!status.is_running) {
					stopPolling();
					// Refresh session list to update title etc.
					await loadSessions();
				}
			} catch {
				stopPolling();
			}
		}, POLL_INTERVAL_MS);
	}

	function stopPolling() {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
		polling = false;
	}

	// ── File upload ───────────────────────────────────────────────────────────

	async function handleFileSelect(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const files = input.files;
		if (!files?.length) return;
		input.value = '';
		fileUploadError = null;

		if (!activeSession) {
			if (!selectedAgent) {
				fileUploadError = t('chat_err_select_agent');
				return;
			}
			try {
				const s = await sessionsApi.create(selectedAgent.id);
				sessions = [s, ...sessions];
				activeSession = s;
				messages = [];
				localStorage.setItem(LAST_SESSION_KEY, s.id);
			} catch (err) {
				fileUploadError = t('chat_err_session_start');
				return;
			}
		}

		fileUploading = true;
		try {
			for (const file of Array.from(files)) {
				const att = await sessionsApi.uploadFile(activeSession.id, file);
				pendingAttachments = [...pendingAttachments, att];
			}
		} catch (err) {
			fileUploadError = err instanceof Error ? err.message : t('chat_err_file_upload');
		} finally {
			fileUploading = false;
		}
	}

	function removeAttachment(idx: number) {
		pendingAttachments = pendingAttachments.filter((_, i) => i !== idx);
	}

	function attachmentIcon(type: string) {
		return type === 'image' ? Image : FileText;
	}

	// ── Messaging ─────────────────────────────────────────────────────────────

	async function send() {
		const content = input.trim();
		if ((!content && pendingAttachments.length === 0) || streaming) return;

		if (!activeSession) {
			if (!selectedAgent) return;
			try {
				const s = await sessionsApi.create(selectedAgent.id);
				sessions = [s, ...sessions];
				activeSession = s;
				messages = [];
				localStorage.setItem(LAST_SESSION_KEY, s.id);
			} catch (err) {
				streamError = err instanceof Error ? err.message : t('chat_err_chat_start');
				return;
			}
		}

		const attachmentsToSend = [...pendingAttachments];
		pendingAttachments = [];
		input = '';
		streaming = true;
		streamingText = '';
		streamingTools = [];
		streamError = null;

		// Optimistic user message
		const displayContent = attachmentsToSend.length
			? (content ? `${content}\n\n` : '') + attachmentsToSend.map(a => `📎 ${a.filename}`).join('\n')
			: content;
		const userMsg: SessionMessage = {
			id: uuid(),
			session_id: activeSession.id,
			role: 'user',
			content: displayContent,
			tool_calls: [],
			tool_results: [],
			tokens_used: null,
			created_at: new Date().toISOString()
		};
		messages = [...messages, userMsg];
		await scrollToBottom();

		abortController = new AbortController();

		try {
			for await (const event of streamMessage(
				activeSession.id,
				content || t('chat_file_ref'),
				abortController.signal,
				attachmentsToSend.length ? attachmentsToSend : undefined,
			)) {
				if (event.type === 'text') {
					streamingText += event.content;
					await scrollToBottom();
				} else if (event.type === 'tool_call') {
					streamingTools = [...streamingTools, { name: event.name, args: event.args }];
					await scrollToBottom();
				} else if (event.type === 'tool_result') {
					streamingTools = streamingTools.map((t) =>
						t.name === event.name && t.result === undefined
							? { ...t, result: event.result }
							: t
					);
					await scrollToBottom();
				} else if (event.type === 'done') {
					const detail = await sessionsApi.get(activeSession.id);
					messages = detail.messages ?? [];
					streamingText = '';
					streamingTools = [];
					sessions = sessions.map((s) =>
						s.id === activeSession!.id ? { ...s, title: detail.title } : s
					);
					await scrollToBottom();
				} else if (event.type === 'error') {
					streamError = event.message ?? t('chat_err_unknown');
					streamingText = '';
					streamingTools = [];
					await scrollToBottom();
				} else if (event.type === 'stream_end') {
					if (!streamError) {
						// Normal completion: reload from DB
						const detail = await sessionsApi.get(activeSession.id);
						messages = detail.messages ?? [];
						streamingText = '';
						streamingTools = [];
					}
					break;
				}
			}
		} catch (e: unknown) {
			if ((e as Error)?.name === 'AbortError') {
				// User navigated away or cancelled; agent keeps running in background
				// Start polling to catch the result when it's done
				if (activeSession) {
					startPolling(activeSession.id);
				}
			} else {
				streamError = e instanceof Error ? e.message : t('chat_err_unexpected');
				streamingText = '';
			}
		} finally {
			streaming = false;
			abortController = null;
		}
	}

	function cancelStream() {
		abortController?.abort();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			send();
		}
	}

	async function scrollToBottom() {
		await tick();
		if (messagesEl) {
			messagesEl.scrollTop = messagesEl.scrollHeight;
		}
	}

	function formatTime(iso: string) {
		return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

<div class="flex h-full bg-background">
	<!-- ── Session sidebar ────────────────────────────────────────────────── -->
	<div class="w-64 border-r border-border flex flex-col flex-shrink-0 bg-muted/20">
		<!-- Agent selector -->
		<div class="p-3 border-b border-border">
			<div class="relative">
				<button
					class="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-background border border-border text-sm hover:bg-muted transition-colors"
					onclick={() => (agentMenuOpen = !agentMenuOpen)}
				>
					<Bot class="w-4 h-4 text-primary flex-shrink-0" />
					<span class="flex-1 text-left truncate text-foreground">
						{selectedAgent?.name ?? t('chat_select_agent_ph')}
					</span>
					<ChevronDown class="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
				</button>

				{#if agentMenuOpen}
					<div
						class="absolute top-full mt-1 left-0 right-0 bg-background border border-border rounded-xl shadow-lg z-20 overflow-hidden"
					>
						{#each agents as agent}
							{@const keyOk = agentHasKey(agent)}
							<button
								class="w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-muted text-left transition-colors"
								onclick={() => {
									selectedAgent = agent;
									agentMenuOpen = false;
									loadAgentInfo(agent);
								}}
							>
								<div
									class="w-6 h-6 rounded-full {keyOk ? 'bg-primary/10' : 'bg-amber-500/10'} flex items-center justify-center flex-shrink-0"
								>
									<Bot class="w-3.5 h-3.5 {keyOk ? 'text-primary' : 'text-amber-500'}" />
								</div>
								<div class="min-w-0 flex-1">
									<div class="font-medium truncate">{agent.name}</div>
									{#if agent.title}
										<div class="text-xs text-muted-foreground truncate">{agent.title}</div>
									{/if}
								</div>
								{#if !keyOk}
									<AlertTriangle class="w-3.5 h-3.5 text-amber-500 flex-shrink-0" title={t('chat_no_key_tooltip')} />
								{/if}
							</button>
						{/each}
						{#if agents.length === 0}
							<div class="px-3 py-4 text-sm text-muted-foreground text-center">
								{t('chat_no_agents')}
							</div>
						{/if}
					</div>
				{/if}
			</div>
		</div>

		<!-- New session button -->
		<div class="p-2 border-b border-border">
			<Button
				variant="outline"
				class="w-full gap-2 text-sm h-9"
				onclick={newSession}
				disabled={!selectedAgent}
			>
				<Plus class="w-3.5 h-3.5" />
				{t('chat_new_session')}
			</Button>
		</div>

		<!-- Session list -->
		<div class="flex-1 overflow-y-auto p-2 space-y-1">
			{#each visibleSessions as s}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<div
					role="button"
					tabindex="0"
					class="w-full text-left px-3 py-2.5 rounded-xl text-sm transition-colors group relative cursor-pointer
						{activeSession?.id === s.id ? 'bg-primary/10 text-primary' : 'hover:bg-muted text-foreground'}"
					onclick={() => openSession(s)}
					onkeydown={(e) => e.key === 'Enter' && openSession(s)}
				>
					<div class="flex items-start gap-2 pr-6">
						<div class="relative flex-shrink-0 mt-0.5">
							<MessageSquare class="w-3.5 h-3.5 opacity-60" />
							{#if s.status === 'running'}
								<span class="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
							{/if}
						</div>
						<div class="min-w-0 flex-1">
							<div class="truncate font-medium text-xs leading-snug">
								{s.title ?? t('chat_session_default')}
							</div>
							{#if s.last_message}
								<div class="truncate text-xs text-muted-foreground mt-0.5">
									{s.last_message.content.slice(0, 40)}
								</div>
							{/if}
						</div>
					</div>
					<!-- Delete button on hover -->
					<button
						class="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 p-1 hover:text-destructive transition-all"
						onclick={(e) => {
							e.stopPropagation();
							closeSession(s);
						}}
					>
						<X class="w-3 h-3" />
					</button>
				</div>
			{/each}
			{#if visibleSessions.length === 0}
				<div class="px-3 py-6 text-center text-xs text-muted-foreground">
					{selectedAgent ? `${t('chat_no_sessions_pre')}${selectedAgent.name}${t('chat_no_sessions_suf')}` : t('chat_no_sessions')}
				</div>
			{/if}
		</div>
	</div>

	<!-- ── Chat area ──────────────────────────────────────────────────────── -->
	<div class="flex-1 flex min-w-0 overflow-hidden">
	<!-- Main chat column -->
	<div class="flex-1 flex flex-col min-w-0">
		{#if activeSession}
			<!-- Header -->
			<div class="px-6 py-4 border-b border-border flex items-center gap-3 flex-shrink-0">
				<div class="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center">
					<Bot class="w-4 h-4 text-primary" />
				</div>
				<div>
					<div class="font-semibold text-sm">{selectedAgent?.name ?? t('chat_agent_fallback')}</div>
					{#if selectedAgent?.title}
						<div class="text-xs text-muted-foreground">{selectedAgent.title}</div>
					{/if}
				</div>
				<div class="ml-auto flex items-center gap-2">
					{#if polling}
						<span class="text-xs text-emerald-600 flex items-center gap-1.5">
							<RefreshCw class="w-3 h-3 animate-spin" />
							{t('chat_bg_running')}
						</span>
					{:else if streaming}
						<span class="text-xs text-muted-foreground flex items-center gap-1.5">
							<Loader2 class="w-3 h-3 animate-spin" />
							{t('chat_responding')}
						</span>
						<button
							class="text-xs text-muted-foreground hover:text-foreground transition-colors"
							onclick={cancelStream}
						>
							{t('chat_stop')}
						</button>
					{/if}
				</div>
			</div>

			<!-- Messages -->
			<div
				bind:this={messagesEl}
				class="flex-1 overflow-y-auto px-6 py-4 space-y-4"
			>
				{#if messages.length === 0 && !streaming && !polling}
					<div class="flex flex-col items-center justify-center h-full text-center text-muted-foreground">
						<Bot class="w-12 h-12 mb-3 opacity-20" />
						<p class="text-sm">{t('chat_start_hint')}</p>
					</div>
				{/if}

				{#each messages as msg (msg.id)}
					{#if msg.role === 'user'}
						<!-- User bubble -->
						<div class="flex justify-end">
							<div class="max-w-[72%]">
								<div class="bg-primary text-primary-foreground rounded-2xl rounded-tr-sm px-4 py-2.5">
									<MessageContent content={msg.content} />
								</div>
								<div class="text-xs text-muted-foreground text-right mt-1 px-1">
									{formatTime(msg.created_at)}
								</div>
							</div>
						</div>
					{:else}
						<!-- Assistant bubble -->
						<div class="flex gap-3">
							<div class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
								<Bot class="w-3.5 h-3.5 text-primary" />
							</div>
							<div class="flex-1 min-w-0">
								{#if msg.tool_calls?.length > 0}
									{#each msg.tool_calls as tc, i}
										<details class="mb-2 rounded-xl border border-border overflow-hidden text-xs" open={false}>
											<summary class="flex items-center gap-2 px-3 py-2 bg-muted/50 font-medium cursor-pointer list-none">
												<Wrench class="w-3 h-3 text-primary flex-shrink-0" />
												<span class="flex-1 font-mono">{tc.name}</span>
												<CheckCircle2 class="w-3 h-3 text-green-500 flex-shrink-0" />
											</summary>
											{#if msg.tool_results?.[i]}
												<div class="px-3 py-2.5 bg-background">
													<MessageContent content={msg.tool_results[i].result} />
												</div>
											{/if}
										</details>
									{/each}
								{/if}
								{#if msg.content}
									<div class="bg-muted/40 rounded-2xl rounded-tl-sm px-4 py-3">
										<MessageContent content={msg.content} />
									</div>
								{/if}
								<div class="text-xs text-muted-foreground mt-1 px-1">
									{formatTime(msg.created_at)}
								</div>
							</div>
						</div>
					{/if}
				{/each}

				<!-- Background polling indicator -->
				{#if polling && !streaming}
					<div class="flex gap-3">
						<div class="w-7 h-7 rounded-full bg-emerald-500/10 flex items-center justify-center flex-shrink-0 mt-0.5">
							<Bot class="w-3.5 h-3.5 text-emerald-600" />
						</div>
						<div class="bg-muted/40 rounded-2xl rounded-tl-sm px-4 py-2.5 flex items-center gap-2">
							<RefreshCw class="w-3.5 h-3.5 animate-spin text-emerald-600" />
							<span class="text-sm text-muted-foreground">{t('chat_polling_label')}</span>
						</div>
					</div>
				{/if}

				<!-- Error response -->
				{#if streamError}
					<div class="flex gap-3">
						<div class="w-7 h-7 rounded-full bg-destructive/10 flex items-center justify-center flex-shrink-0 mt-0.5">
							<Bot class="w-3.5 h-3.5 text-destructive" />
						</div>
						<div class="flex-1 min-w-0">
							<div class="bg-destructive/8 border border-destructive/20 rounded-2xl rounded-tl-sm px-4 py-3">
								<p class="text-sm text-destructive font-medium mb-1">{t('chat_error_title')}</p>
								<p class="text-xs text-destructive/80">{streamError}</p>
							</div>
						</div>
					</div>
				{/if}

				<!-- Live streaming response -->
				{#if streaming}
					<div class="flex gap-3">
						<div class="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
							<Bot class="w-3.5 h-3.5 text-primary" />
						</div>
						<div class="flex-1 min-w-0">
							{#each streamingTools as t}
								<div class="mb-2 rounded-xl border border-border overflow-hidden text-xs">
									<div class="flex items-center gap-2 px-3 py-2 bg-muted/50 font-medium">
										<Wrench class="w-3 h-3 text-primary" />
										<span>{t.name}</span>
										{#if t.result === undefined}
											<Loader2 class="w-3 h-3 animate-spin ml-auto" />
										{:else}
											<CheckCircle2 class="w-3 h-3 text-green-500 ml-auto" />
										{/if}
									</div>
									{#if t.result !== undefined}
										<div class="px-3 py-2.5 bg-background">
											<MessageContent content={t.result} />
										</div>
									{/if}
								</div>
							{/each}

							{#if streamingText}
								<div class="bg-muted/40 rounded-2xl rounded-tl-sm px-4 py-3">
									<MessageContent content={streamingText} streaming={true} />
									<span class="inline-block w-0.5 h-3.5 bg-foreground/60 ml-0.5 animate-pulse align-text-bottom"></span>
								</div>
							{:else if streamingTools.length === 0}
								<div class="bg-muted/40 rounded-2xl rounded-tl-sm px-4 py-2.5">
									<Loader2 class="w-4 h-4 animate-spin text-muted-foreground" />
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>

			<!-- Input -->
			<div class="px-6 py-4 border-t border-border flex-shrink-0">

				<!-- File upload error -->
				{#if fileUploadError}
					<div class="flex items-center gap-2 px-3 py-2 mb-2 rounded-xl bg-destructive/10 border border-destructive/20 text-xs text-destructive">
						<AlertTriangle class="w-3.5 h-3.5 flex-shrink-0" />
						<span>{fileUploadError}</span>
						<button class="ml-auto" onclick={() => (fileUploadError = null)}><X class="w-3 h-3" /></button>
					</div>
				{/if}

				<!-- Attachment chips -->
				{#if pendingAttachments.length > 0}
					<div class="flex flex-wrap gap-2 mb-2">
						{#each pendingAttachments as att, i}
							{@const Icon = attachmentIcon(att.type)}
							<div class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-muted border border-border text-xs">
								<Icon class="w-3 h-3 text-muted-foreground flex-shrink-0" />
								<span class="max-w-[120px] truncate">{att.filename}</span>
								<button
									class="text-muted-foreground hover:text-destructive transition-colors ml-0.5"
									onclick={() => removeAttachment(i)}
								>
									<X class="w-3 h-3" />
								</button>
							</div>
						{/each}
					</div>
				{/if}

				{#if selectedAgent && !agentHasKey(selectedAgent)}
					<div class="flex items-center gap-2 px-3 py-2 mb-2 rounded-xl bg-amber-500/10 border border-amber-500/20 text-xs text-amber-700 dark:text-amber-400">
						<AlertTriangle class="w-3.5 h-3.5 flex-shrink-0" />
						<span>{t('chat_no_key_pre')} <strong>{selectedAgent.agent_config?.model}</strong> {t('chat_no_key_mid')} <a href="/settings" class="underline">{t('chat_no_key_link')}</a>{t('chat_no_key_post')}</span>
					</div>
				{/if}

				<div class="flex items-end gap-3 bg-muted/30 rounded-2xl border border-border px-4 py-3 focus-within:border-primary/50 transition-colors">
					<!-- File upload button -->
					<button
						type="button"
						class="flex-shrink-0 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
						title={t('chat_file_attach_title')}
						disabled={streaming || polling}
						onclick={() => fileInputEl?.click()}
					>
						{#if fileUploading}
							<Loader2 class="w-4 h-4 animate-spin" />
						{:else}
							<Paperclip class="w-4 h-4" />
						{/if}
					</button>

					<textarea
						bind:this={inputEl}
						bind:value={input}
						onkeydown={handleKeydown}
						placeholder={t('chat_input_ph')}
						rows={1}
						disabled={streaming || polling}
						class="flex-1 bg-transparent text-sm resize-none outline-none placeholder:text-muted-foreground min-h-[20px] max-h-[120px] leading-5 disabled:opacity-50"
						style="height: auto; overflow-y: hidden;"
						oninput={(e) => {
							const t = e.currentTarget;
							t.style.height = 'auto';
							t.style.height = Math.min(t.scrollHeight, 120) + 'px';
						}}
					></textarea>
					<Button
						size="sm"
						onclick={send}
						disabled={(!input.trim() && pendingAttachments.length === 0) || streaming || polling}
						class="rounded-xl h-8 w-8 p-0 flex-shrink-0"
					>
						<Send class="w-3.5 h-3.5" />
					</Button>
				</div>
				<p class="text-xs text-muted-foreground text-center mt-2">
					{selectedAgent?.name ?? t('chat_agent_fallback')} {t('chat_footer_suffix')}
				</p>
			</div>
		{:else}
			<!-- Empty state - no active session -->
			<div class="flex-1 flex flex-col items-center justify-center text-muted-foreground p-8">
				<div class="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
					<MessageSquare class="w-8 h-8 text-primary/50" />
				</div>
				<h2 class="text-lg font-semibold text-foreground mb-1">{t('chat_start_title')}</h2>
				<p class="text-sm text-center max-w-sm mb-6">
					{t('chat_start_desc')}
				</p>
				{#if selectedAgent}
					<Button onclick={newSession} class="gap-2">
						<Plus class="w-4 h-4" />
						{t('chat_start_with_pre')}{selectedAgent.name}{t('chat_start_with_suf')}
					</Button>
				{:else if agents.length > 0}
					<p class="text-sm">{t('chat_select_from_panel')}</p>
				{:else}
					<p class="text-sm">
						{t('chat_no_agents_pre')} <a href="/agents" class="text-primary underline">{t('chat_no_agents_link')}</a> {t('chat_no_agents_post')}
					</p>
				{/if}
			</div>
		{/if}
	</div>

	<!-- ── Agent Info Panel ───────────────────────────────────────────────── -->
	{#if selectedAgent && infoPanelOpen}
		<div class="w-72 border-l border-border flex flex-col flex-shrink-0 bg-muted/10 overflow-y-auto">
			<!-- Agent card -->
			<div class="p-4 border-b border-border">
				<div class="flex items-center justify-between mb-3">
					<span class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('chat_info_title')}</span>
					<button
						class="text-muted-foreground hover:text-foreground transition-colors"
						onclick={() => (infoPanelOpen = false)}
					>
						<X class="w-3.5 h-3.5" />
					</button>
				</div>
				<div class="flex items-center gap-2.5">
					<div class="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
						<Bot class="w-4.5 h-4.5 text-primary" />
					</div>
					<div class="min-w-0">
						<div class="font-semibold text-sm truncate">{selectedAgent.name}</div>
						{#if selectedAgent.title}
							<div class="text-xs text-muted-foreground truncate">{selectedAgent.title}</div>
						{/if}
					</div>
				</div>

				{#if selectedAgent.agent_config}
					{@const cfg = selectedAgent.agent_config}
					<div class="mt-3 flex flex-wrap gap-1.5">
						<span class="px-2 py-0.5 rounded-full text-xs bg-muted border border-border font-mono">
							{cfg.model}
						</span>
						<span class="px-2 py-0.5 rounded-full text-xs border font-medium
							{cfg.status === 'active' ? 'bg-green-50 text-green-700 border-green-200' :
							 cfg.status === 'draft'  ? 'bg-amber-50 text-amber-700 border-amber-200' :
							                          'bg-muted text-muted-foreground border-border'}">
							{cfg.status === 'active' ? t('status_active') : cfg.status === 'draft' ? t('status_draft') : t('status_inactive')}
						</span>
					</div>
				{/if}
			</div>

			<!-- Skills -->
			{#if agentSkills.length > 0}
				<div class="p-4 border-b border-border">
					<div class="flex items-center gap-1.5 mb-2.5">
						<Zap class="w-3.5 h-3.5 text-primary" />
						<span class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('chat_tools_skills')}</span>
					</div>
					<div class="space-y-1.5">
						{#each agentSkills as skill}
							<div class="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-background border border-border/60">
								<div class="flex-1 min-w-0">
									<div class="flex items-center gap-1.5">
										<span class="text-xs font-medium truncate">{skill.name}</span>
										{#if !skill.is_active}
											<span class="text-xs text-muted-foreground">{t('chat_skill_inactive')}</span>
										{/if}
									</div>
									{#if skill.description}
										<div class="text-xs text-muted-foreground mt-0.5 leading-snug">{skill.description}</div>
									{/if}
								</div>
								<span class="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wide
									{skill.skill_type === 'builtin' ? 'bg-blue-50 text-blue-600' :
									 skill.skill_type === 'mcp'     ? 'bg-purple-50 text-purple-600' :
									 skill.skill_type === 'http'    ? 'bg-green-50 text-green-600' :
									                                   'bg-orange-50 text-orange-600'}">
									{skill.skill_type}
								</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- Department -->
			{#if selectedAgent.department_name}
				<div class="p-4">
					<div class="flex items-center gap-1.5 mb-2.5">
						<Shield class="w-3.5 h-3.5 text-primary" />
						<span class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('chat_department')}</span>
					</div>
					<div class="flex items-center gap-2 px-2.5 py-2 rounded-lg bg-background border border-border/60 mb-2">
						<span class="text-xs font-medium">{selectedAgent.department_name}</span>
					</div>
					{#if selectedAgent.manager_name}
						<div class="text-xs text-muted-foreground">
							{t('chat_manager')} {selectedAgent.manager_name}
						</div>
					{/if}
				</div>
			{/if}
		</div>
	{:else if selectedAgent && !infoPanelOpen}
		<!-- Collapsed toggle -->
		<div class="w-8 border-l border-border flex flex-col items-center pt-4 flex-shrink-0 bg-muted/10">
			<button
				class="text-muted-foreground hover:text-foreground transition-colors p-1"
				onclick={() => (infoPanelOpen = true)}
				title={t('chat_show_info')}
			>
				<Info class="w-4 h-4" />
			</button>
		</div>
	{/if}
	</div>
</div>

<!-- Hidden file input -->
<input
	bind:this={fileInputEl}
	type="file"
	accept=".pdf,.txt,.csv,image/*"
	multiple
	class="hidden"
	onchange={handleFileSelect}
/>

<!-- Click outside to close agent menu -->
{#if agentMenuOpen}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="fixed inset-0 z-10" onclick={() => (agentMenuOpen = false)}></div>
{/if}
