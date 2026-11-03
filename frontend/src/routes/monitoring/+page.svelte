<script lang="ts">
	import { monitoringApi, type Monitoring, type Status } from '$lib/api/monitoring';
	import { companyStore } from '$lib/stores/company.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import Button from '$lib/components/ui/button.svelte';
	import { latestRequest } from '$lib/latest-request';
	import { Loader } from '@lucide/svelte';

	const activeCompanyId = $derived(companyStore.active?.id ?? '');

	let data: Monitoring | null = $state(null);
	let loading = $state(false);
	let error: string | null = $state(null);

	const LABEL: Record<Status, string> = { ok: 'Sağlıklı', warn: 'Dikkat', fail: 'Sorun var', unknown: 'Bilinmiyor' };
	const VARIANT: Record<Status, 'default' | 'secondary' | 'destructive' | 'outline'> = {
		ok: 'default',
		warn: 'secondary',
		fail: 'destructive',
		unknown: 'outline'
	};
	const ANCHOR: Record<string, string> = {
		ok: 'Dış çapa ile uyumlu',
		none_recorded: 'Henüz çapalanmadı (kısaltmaya karşı korumasız)',
		truncated: 'KISALTILMIŞ: zincir çapadan kısa',
		rewritten: 'YENİDEN YAZILMIŞ: çapadaki kayıt değişmiş',
		missing: 'Zincir çapadan sonra kaybolmuş'
	};
	const REASON: Record<string, string> = {
		no_reports: 'Henüz hiçbir istemci durum bildirmedi (3pa workspace sync sonrası otomatik gönderilir).',
		no_live_sessions: 'Şu an çalışan 3pa oturumu yok.',
		policy_not_checked: 'Çalışan oturumlar politika denetimi öncesi sürümden; hazır olup olmadıkları bilinmiyor.',
		section_failed: 'Bu bölüm hesaplanamadı; ayrıntı sunucu günlüğünde.'
	};
	const NOT_READY: Record<string, string> = {
		invalid_mode: 'politika modu geçersiz',
		scope_unreadable: 'kapsam okunamadı',
		policy_unreadable: 'politika okunamadı',
		policy_malformed: 'politika bloğu bozuk'
	};
	const LAYERS: Record<string, string> = { model: 'Model', prompt: 'Prompt', tool: 'Araç', policy: 'Politika' };

	const num = (n: number) => n.toLocaleString('tr-TR');

	const requests = latestRequest<string>();

	async function load(deep = false) {
		const id = activeCompanyId;
		const req = requests.begin(id);
		data = null;
		error = null;
		if (!id) {
			loading = false;
			return;
		}
		loading = true;
		try {
			const result = await monitoringApi.get(id, deep);
			if (req.isCurrent(activeCompanyId)) data = result;
		} catch (e) {
			if (req.isCurrent(activeCompanyId)) error = (e as Error).message;
		} finally {
			if (req.isLatest()) loading = false;
		}
	}

	$effect(() => {
		// reads activeCompanyId, so a company change reloads (and an empty one clears the screen)
		void activeCompanyId;
		load();
	});
</script>

<svelte:head><title>İzleme • fab.engineering</title></svelte:head>

<div class="space-y-6">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<h1 class="font-display text-3xl tracking-tight">İzleme</h1>
			<p class="text-sm text-muted-foreground mt-1">
				Mevcut görünümlerin tek ekranda özeti. Yeni bir ölçüm yapılmaz; ölçülemeyen şey
				<strong>bilinmiyor</strong> olarak gösterilir.
			</p>
		</div>
		<div class="flex items-center gap-2">
			{#if data}<Badge variant={VARIANT[data.status]}>{LABEL[data.status]}</Badge>{/if}
			<Button variant="outline" onclick={() => load(false)} disabled={loading}>Yenile</Button>
			<Button variant="outline" onclick={() => load(true)} disabled={loading}
				title="Denetim zincirinin tamamını yeniden hesaplar (uzun sürebilir)">Zinciri tam doğrula</Button>
		</div>
	</div>

	{#if error}<p class="text-sm text-destructive" role="alert">{error}</p>{/if}
	{#if loading}<Loader class="w-4 h-4 animate-spin" aria-label="Yükleniyor" />{/if}

	{#if data}
		{@const s = data.sections}
		<div class="grid gap-4 md:grid-cols-2">
			<section class="rounded-lg border p-4 space-y-1" aria-label="Hizmet">
				<div class="flex items-center justify-between">
					<h2 class="font-medium">Hizmet</h2>
					<Badge variant={VARIANT[s.service.status]}>{LABEL[s.service.status]}</Badge>
				</div>
				<p class="text-sm text-muted-foreground">Sürüm {s.service.version} · veritabanı {s.service.database === 'ok' ? 'erişilebilir' : 'erişilemiyor'}</p>
			</section>

			<section class="rounded-lg border p-4 space-y-1" aria-label="Denetim zinciri">
				<div class="flex items-center justify-between">
					<h2 class="font-medium">Denetim zinciri</h2>
					<Badge variant={VARIANT[s.audit.status]}>{LABEL[s.audit.status]}</Badge>
				</div>
				{#if s.audit.reason}
					<p class="text-sm text-muted-foreground">{REASON[s.audit.reason] ?? s.audit.reason}</p>
				{:else}
					<p class="text-sm">{num(s.audit.events)} olay · {ANCHOR[s.audit.anchor] ?? s.audit.anchor}</p>
					<p class="text-sm text-muted-foreground">
						{#if s.audit.verified === null}Tam doğrulama bu istekte yapılmadı.
						{:else if s.audit.verified}Tam doğrulama geçti.
						{:else}Tam doğrulama BAŞARISIZ: {s.audit.broken_at}. kayıtta kırılma.{/if}
					</p>
				{/if}
			</section>

			<section class="rounded-lg border p-4 space-y-2" aria-label="Ağ geçidi kullanımı">
				<div class="flex items-center justify-between">
					<h2 class="font-medium">Ağ geçidi kullanımı</h2>
					<Badge variant={VARIANT[s.gateway.status]}>{LABEL[s.gateway.status]}</Badge>
				</div>
				{#if s.gateway.reason}
					<p class="text-sm text-muted-foreground">{REASON[s.gateway.reason] ?? s.gateway.reason}</p>
				{:else}
					<p class="text-sm">Bugün {num(s.gateway.day.requests)} istek · {num(s.gateway.day.tokens_in + s.gateway.day.tokens_out)} token</p>
					<p class="text-sm">Bu ay {num(s.gateway.month.requests)} istek · {num(s.gateway.month.tokens_in + s.gateway.month.tokens_out)} token</p>
					{#if s.gateway.top_agents_today.length}
						<ul class="text-sm text-muted-foreground">
							{#each s.gateway.top_agents_today as a (a.persona_id)}
								<li>{a.name ?? a.persona_id} — {num(a.tokens)} token</li>
							{/each}
						</ul>
					{/if}
				{/if}
			</section>

			<section class="rounded-lg border p-4 space-y-1" aria-label="Değerlendirme">
				<div class="flex items-center justify-between">
					<h2 class="font-medium">Değerlendirme</h2>
					<Badge variant={VARIANT[s.eval.status]}>{LABEL[s.eval.status]}</Badge>
				</div>
				{#if s.eval.reason}
					<p class="text-sm text-muted-foreground">{REASON[s.eval.reason] ?? s.eval.reason}</p>
				{:else}
					<p class="text-sm">Son {s.eval.days} gün: {num(s.eval.runs)} tanı</p>
					{#if Object.keys(s.eval.suspect_counts).length}
						<p class="text-sm text-muted-foreground">
							Şüpheli katman (varsayım, hata oranı değil):
							{#each Object.entries(s.eval.suspect_counts) as [k, n], i (k)}{i ? ' · ' : ''}{LAYERS[k] ?? k} {n}{/each}
						</p>
					{/if}
				{/if}
			</section>

			<section class="rounded-lg border p-4 space-y-1" aria-label="Çalışma alanı imzalama">
				<div class="flex items-center justify-between">
					<h2 class="font-medium">Çalışma alanı imzalama</h2>
					<Badge variant={VARIANT[s.workspace.status]}>{LABEL[s.workspace.status]}</Badge>
				</div>
				{#if s.workspace.reason}
					<p class="text-sm text-muted-foreground">{REASON[s.workspace.reason] ?? s.workspace.reason}</p>
				{:else if s.workspace.signer === 'unavailable'}
					<p class="text-sm">İmzalama anahtarı kullanılamıyor (kod: {(s.workspace as { reason?: string }).reason ?? '—'}).</p>
				{:else}
					<p class="text-sm">Dönem {s.workspace.epoch} · iptal listesi #{s.workspace.crl_number} · sertifikada {s.workspace.signing_cert_days_left} gün kaldı</p>
				{/if}
				<p class="text-sm text-muted-foreground">
					{s.workspace.people_issued} kişiye çalışma alanı verildi{#if s.workspace.last_issued}, son: {new Date(s.workspace.last_issued).toLocaleString('tr-TR')}{/if}
				</p>
			</section>

			<section class="rounded-lg border p-4 space-y-1" aria-label="İstemciler">
				<div class="flex items-center justify-between">
					<h2 class="font-medium">İstemciler (sapma)</h2>
					<Badge variant={VARIANT[s.clients.status]}>{LABEL[s.clients.status]}</Badge>
				</div>
				<p class="text-xs text-muted-foreground">Kendi bildirimleri: bir tanı sinyalidir, kanıt değildir. Dosya adı içermez, yalnız sayılar.</p>
				{#if s.clients.reason}
					<p class="text-sm text-muted-foreground">{REASON[s.clients.reason] ?? s.clients.reason}</p>
				{/if}
				{#if s.clients.issued !== undefined}
				<p class="text-sm">
					{s.clients.reporting}/{s.clients.issued} kişi bildirdi · {s.clients.never_reported} kişi henüz hiç bildirmedi ·
					{s.clients.silent} kişi {s.clients.not_reported_for_days}+ gündür bildirmedi
					{#if s.clients.behind !== undefined} · {s.clients.behind} kişi güncel sürümün gerisinde{/if}
				</p>
				{/if}
				{#if !s.clients.reason}
					{#if s.clients.drifting}
						<p class="text-sm">{s.clients.drifting} kişide sapma var:</p>
						<ul class="text-sm text-muted-foreground">
							{#each s.clients.drifting_people ?? [] as d, i (i)}
								<li>
									{d.name ?? 'bilinmeyen'} — eksik {d.missing}, değişmiş {d.modified}, fazla {d.extra}, yabancı mod {d.unmanaged}{d.interrupted ? ', yarım kalmış güncelleme' : ''}
								</li>
							{/each}
						</ul>
					{/if}
				{/if}
			</section>

			<section class="rounded-lg border p-4 space-y-1" aria-label="Oturumlar">
				<div class="flex items-center justify-between">
					<h2 class="font-medium">Oturumlar (canlı ve politika hazır)</h2>
					<Badge variant={VARIANT[s.sessions.status]}>{LABEL[s.sessions.status]}</Badge>
				</div>
				<p class="text-xs text-muted-foreground">Canlı = son {Math.round((s.sessions.alive_within_seconds ?? 300) / 60)} dakikada sinyal verdi. Hazır = sunucu o kişinin politikasını o anda okuyup uygulayabildi (cihaz hakkında bir kanıt değildir). Hazır olmayan oturumda araç çağrıları reddedilir.</p>
				{#if s.sessions.reason}
					<p class="text-sm text-muted-foreground">{REASON[s.sessions.reason] ?? s.sessions.reason}</p>
				{/if}
				{#if s.sessions.alive !== undefined}
					<p class="text-sm">
						{s.sessions.alive} canlı oturum · {s.sessions.ready} hazır · {s.sessions.not_ready} hazır değil{#if s.sessions.unchecked} · {s.sessions.unchecked} denetlenmemiş{/if}
					</p>
				{/if}
				{#if s.sessions.not_ready_sessions?.length}
					<ul class="text-sm text-muted-foreground">
						{#each s.sessions.not_ready_sessions as n, i (i)}
							<li>{n.name ?? 'bilinmeyen'} — {NOT_READY[n.reason] ?? n.reason}</li>
						{/each}
					</ul>
				{/if}
			</section>
		</div>
		<p class="text-xs text-muted-foreground">Oluşturulma: {new Date(data.generated_at).toLocaleString('tr-TR')}</p>
	{/if}
</div>
