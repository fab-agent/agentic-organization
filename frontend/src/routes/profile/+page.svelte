<script lang="ts">
	import Button from '$lib/components/ui/button.svelte';
	import Input from '$lib/components/ui/input.svelte';
	import Badge from '$lib/components/ui/badge.svelte';
	import { Camera, KeyRound, Target, ShieldCheck, Plus, X, Save, Eye, EyeOff, Layers, CheckCircle2 } from '@lucide/svelte';

	// ── Active tab ────────────────────────────────────────────────────────────
	type Tab = 'profile' | 'security' | 'guide';
	let activeTab: Tab = $state('profile');

	// ── Profile ───────────────────────────────────────────────────────────────
	let profile = $state({
		firstName: 'Kuntay',
		lastName:  'Kunt',
		email:     'bilgi@kuntaykunt.com',
		title:     'CEO & Co-Founder',
		phone:     '+90 555 000 00 00',
		timezone:  'Europe/Istanbul',
	});
	let profileSaved = $state(false);

	function saveProfile() {
		profileSaved = true;
		setTimeout(() => (profileSaved = false), 2500);
	}

	// ── Password ──────────────────────────────────────────────────────────────
	let passwords = $state({ current: '', next: '', confirm: '' });
	let showCurrent  = $state(false);
	let showNext     = $state(false);
	let showConfirm  = $state(false);
	let pwError: string | null = $state(null);
	let pwSaved = $state(false);

	const pwStrength = $derived(() => {
		const p = passwords.next;
		if (!p) return 0;
		let s = 0;
		if (p.length >= 8) s++;
		if (/[A-Z]/.test(p)) s++;
		if (/[0-9]/.test(p)) s++;
		if (/[^A-Za-z0-9]/.test(p)) s++;
		return s;
	});

	const pwStrengthLabel = $derived(() => (['', 'Zayıf', 'Orta', 'İyi', 'Güçlü'] as const)[pwStrength()]);
	const pwStrengthColor = $derived(() => (['', 'bg-red-400', 'bg-orange-400', 'bg-yellow-400', 'bg-emerald-500'] as const)[pwStrength()]);

	function savePassword() {
		pwError = null;
		if (!passwords.current) { pwError = 'Mevcut şifreyi girin.'; return; }
		if (passwords.next.length < 8) { pwError = 'Yeni şifre en az 8 karakter olmalı.'; return; }
		if (passwords.next !== passwords.confirm) { pwError = 'Şifreler eşleşmiyor.'; return; }
		passwords = { current: '', next: '', confirm: '' };
		pwSaved = true;
		setTimeout(() => (pwSaved = false), 2500);
	}

	// ── Work Scope ────────────────────────────────────────────────────────────
	const ALL_DEPTS = ['Yazılım Geliştirme', 'Kalite Güvence', 'Pazarlama & Büyüme', 'Finans & Operasyon', 'İnsan Kaynakları', 'Müşteri Başarısı'];

	let scope = $state({
		departments: ['Yazılım Geliştirme', 'Pazarlama & Büyüme', 'Finans & Operasyon'],
		role: 'executive',  // 'executive' | 'manager' | 'contributor'
	});

	function toggleDept(dept: string) {
		if (scope.departments.includes(dept)) {
			scope.departments = scope.departments.filter(d => d !== dept);
		} else {
			scope.departments = [...scope.departments, dept];
		}
	}

	// ── Work Guide ────────────────────────────────────────────────────────────
	let guide = $state(`# Çalışma Rehberi

## Yanıt Tercihleri
- Her zaman Türkçe yanıt ver
- Önce kısa özet, ardından detay ver
- Teknik konularda somut örnekler kullan
- Belirsizlik varsa sormadan ilerlemek yerine netleştir

## Karar Alma Prensipleri
- Yazılım kararlarında güvenlik ve geri alınabilirlik ön planda olsun
- Hızlı MVP > mükemmel ama geç çözüm
- Değişikliklerde tahmini etki büyüklüğünü belirt
- Maliyet-fayda dengesini her öneride göz önünde bulundur

## Kapsam ve Sınırlar
- Finans verileri için her zaman CFO onayını bekle
- Müşteri verisi içeren analizlerde KVKK uyumluluğunu kontrol et
- Dış servis entegrasyonlarında güvenlik açığı değerlendirmesi yap

## İletişim Stili
- Madde madde net listeler kullan
- Jargon kullanacaksan parantez içinde Türkçe karşılığını yaz
- Uzun yanıtlarda başlık (##) yapısını koru`);

	const GUIDE_SUGGESTIONS = [
		'Her zaman Türkçe yanıt ver',
		'Önce özet, sonra detay ver',
		'Kod önerilerinde test senaryosu da ekle',
		'Hata durumlarında kök neden analizi yap',
		'Önemli kararları adım adım açıkla',
		'Belirsizlik varsa netleştirici soru sor',
		'Her öneride olası riskleri belirt',
		'Maliyet etkisini her fırsatta hesapla',
	];

	function addSuggestion(s: string) {
		if (guide.includes(s)) return;
		guide = guide + `\n- ${s}`;
	}

	let guideSaved = $state(false);
	function saveGuide() {
		guideSaved = true;
		setTimeout(() => (guideSaved = false), 2500);
	}

	// ── Avatar ────────────────────────────────────────────────────────────────
	const initials = $derived(`${profile.firstName[0]}${profile.lastName[0]}`);
</script>

<svelte:head>
	<title>Profil • 3rdParty Agent</title>
</svelte:head>

<div class="space-y-6 max-w-3xl">

	<!-- Header + Avatar -->
	<div class="flex flex-col sm:flex-row sm:items-center gap-5">
		<!-- Avatar -->
		<div class="relative flex-shrink-0">
			<div class="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center text-2xl font-bold text-primary select-none">
				{initials}
			</div>
			<button
				class="absolute -bottom-1.5 -right-1.5 w-7 h-7 rounded-full bg-card border-2 border-background shadow flex items-center justify-center hover:bg-muted transition-colors"
				aria-label="Fotoğraf değiştir"
				title="Fotoğraf değiştir"
			>
				<Camera class="w-3.5 h-3.5 text-muted-foreground" />
			</button>
		</div>

		<div>
			<h1 class="font-display text-3xl tracking-tight">{profile.firstName} {profile.lastName}</h1>
			<p class="text-muted-foreground mt-0.5">{profile.title}</p>
			<div class="flex items-center gap-2 mt-2">
				<Badge variant="secondary">{profile.email}</Badge>
				<Badge variant="outline">CEO</Badge>
			</div>
		</div>
	</div>

	<!-- Tabs -->
	<div class="flex gap-1 border-b">
		{#each [
			{ id: 'profile',  label: 'Kişisel Bilgiler' },
			{ id: 'security', label: 'Güvenlik' },
			{ id: 'guide',    label: 'Work Scope & Guide' },
		] as tab}
			<button
				onclick={() => (activeTab = tab.id as Tab)}
				class={[
					'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors',
					activeTab === tab.id
						? 'border-primary text-primary'
						: 'border-transparent text-muted-foreground hover:text-foreground'
				].join(' ')}
			>
				{tab.label}
			</button>
		{/each}
	</div>

	<!-- ── Tab: Kişisel Bilgiler ────────────────────────────────────────────── -->
	{#if activeTab === 'profile'}
		<div class="rounded-xl border bg-card p-6 space-y-5">
			<div class="grid sm:grid-cols-2 gap-4">
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="first-name">Ad</label>
					<Input id="first-name" bind:value={profile.firstName} />
				</div>
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="last-name">Soyad</label>
					<Input id="last-name" bind:value={profile.lastName} />
				</div>
				<div class="space-y-1.5 sm:col-span-2">
					<label class="text-sm font-medium" for="email">E-posta</label>
					<Input id="email" type="email" bind:value={profile.email} />
				</div>
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="title">Unvan</label>
					<Input id="title" bind:value={profile.title} placeholder="CEO & Co-Founder" />
				</div>
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="phone">Telefon</label>
					<Input id="phone" type="tel" bind:value={profile.phone} />
				</div>
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="timezone">Saat Dilimi</label>
					<select id="timezone" bind:value={profile.timezone}
						class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
						<option value="Europe/Istanbul">Europe/Istanbul (UTC+3)</option>
						<option value="UTC">UTC</option>
						<option value="Europe/London">Europe/London (UTC+0/+1)</option>
						<option value="America/New_York">America/New_York (UTC-5/-4)</option>
					</select>
				</div>
			</div>

			<div class="flex items-center justify-end gap-3 pt-2">
				{#if profileSaved}
					<span class="text-sm text-emerald-600 flex items-center gap-1.5">
						<CheckCircle2 class="w-4 h-4" /> Kaydedildi
					</span>
				{/if}
				<Button onclick={saveProfile}>
					<Save class="w-4 h-4" />
					Kaydet
				</Button>
			</div>
		</div>

	<!-- ── Tab: Güvenlik ────────────────────────────────────────────────────── -->
	{:else if activeTab === 'security'}
		<div class="rounded-xl border bg-card p-6 space-y-5">
			<div>
				<h2 class="font-semibold">Şifre Değiştir</h2>
				<p class="text-sm text-muted-foreground mt-0.5">Hesap güvenliğiniz için güçlü bir şifre kullanın.</p>
			</div>

			<div class="space-y-4 max-w-sm">
				<!-- Current password -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="pw-current">Mevcut Şifre</label>
					<div class="relative">
						<Input id="pw-current" type={showCurrent ? 'text' : 'password'} bind:value={passwords.current} class="pr-10" />
						<button type="button" onclick={() => (showCurrent = !showCurrent)}
							class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
							aria-label={showCurrent ? 'Gizle' : 'Göster'}>
							{#if showCurrent}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
						</button>
					</div>
				</div>

				<!-- New password -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="pw-new">Yeni Şifre</label>
					<div class="relative">
						<Input id="pw-new" type={showNext ? 'text' : 'password'} bind:value={passwords.next} class="pr-10" />
						<button type="button" onclick={() => (showNext = !showNext)}
							class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
							aria-label={showNext ? 'Gizle' : 'Göster'}>
							{#if showNext}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
						</button>
					</div>
					<!-- Strength bar -->
					{#if passwords.next}
						<div class="space-y-1">
							<div class="flex gap-1">
								{#each [1,2,3,4] as n}
									<div class="h-1 flex-1 rounded-full {n <= pwStrength() ? pwStrengthColor() : 'bg-muted'} transition-all"></div>
								{/each}
							</div>
							<p class="text-xs text-muted-foreground">{pwStrengthLabel()}</p>
						</div>
					{/if}
				</div>

				<!-- Confirm -->
				<div class="space-y-1.5">
					<label class="text-sm font-medium" for="pw-confirm">Şifre Tekrar</label>
					<div class="relative">
						<Input id="pw-confirm" type={showConfirm ? 'text' : 'password'} bind:value={passwords.confirm} class="pr-10" />
						<button type="button" onclick={() => (showConfirm = !showConfirm)}
							class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
							aria-label={showConfirm ? 'Gizle' : 'Göster'}>
							{#if showConfirm}<EyeOff class="w-4 h-4" />{:else}<Eye class="w-4 h-4" />{/if}
						</button>
					</div>
					{#if passwords.confirm && passwords.next !== passwords.confirm}
						<p class="text-xs text-destructive">Şifreler eşleşmiyor</p>
					{/if}
				</div>
			</div>

			{#if pwError}
				<p class="text-sm text-destructive">{pwError}</p>
			{/if}

			<div class="flex items-center gap-3 pt-1">
				{#if pwSaved}
					<span class="text-sm text-emerald-600 flex items-center gap-1.5">
						<CheckCircle2 class="w-4 h-4" /> Şifre güncellendi
					</span>
				{/if}
				<Button onclick={savePassword}>
					<KeyRound class="w-4 h-4" />
					Şifreyi Güncelle
				</Button>
			</div>

			<!-- Divider + Sessions section -->
			<div class="border-t pt-5 space-y-3">
				<div>
					<h3 class="font-semibold text-sm">Aktif Oturumlar</h3>
					<p class="text-xs text-muted-foreground mt-0.5">Hesabınıza bağlı cihazlar</p>
				</div>
				<div class="space-y-2">
					{#each [
						{ device: 'Chrome / macOS', ip: '95.216.158.12', current: true },
						{ device: 'Safari / iPhone', ip: '78.180.42.11',  current: false },
					] as session}
						<div class="flex items-center justify-between px-3 py-2.5 rounded-lg border bg-muted/30 text-sm">
							<div>
								<div class="font-medium">{session.device}</div>
								<div class="text-xs text-muted-foreground">{session.ip}</div>
							</div>
							{#if session.current}
								<Badge variant="secondary">Aktif oturum</Badge>
							{:else}
								<Button variant="ghost" size="sm" class="text-destructive hover:text-destructive h-7 text-xs">Sonlandır</Button>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		</div>

	<!-- ── Tab: Work Scope & Guide ───────────────────────────────────────────── -->
	{:else if activeTab === 'guide'}
		<div class="space-y-5">

			<!-- Scope -->
			<div class="rounded-xl border bg-card p-6 space-y-4">
				<div>
					<h2 class="font-semibold">Çalışma Kapsamı</h2>
					<p class="text-sm text-muted-foreground mt-0.5">
						Bu kullanıcının erişim ve öncelik alanlarını belirler. Ajanlar bu kapsama göre bağlamı daraltır.
					</p>
				</div>

				<div class="space-y-2">
					<div class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Departmanlar</div>
					<div class="flex flex-wrap gap-2">
						{#each ALL_DEPTS as dept}
							<button
								type="button"
								onclick={() => toggleDept(dept)}
								class={[
									'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-sm font-medium transition-colors',
									scope.departments.includes(dept)
										? 'bg-indigo-50 border-indigo-300 text-indigo-700'
										: 'bg-background border-border text-muted-foreground hover:border-indigo-300 hover:text-indigo-600'
								].join(' ')}
							>
								<Layers class="w-3 h-3" />
								{dept}
							</button>
						{/each}
					</div>
				</div>

				<div class="space-y-2">
					<div class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Rol Seviyesi</div>
					<div class="flex gap-2">
						{#each [
							{ id: 'executive',   label: 'Yönetici',     desc: 'Tüm veriler, stratejik kararlar' },
							{ id: 'manager',     label: 'Müdür',        desc: 'Departman verisi, taktik kararlar' },
							{ id: 'contributor', label: 'Katkıcı',      desc: 'Sınırlı veri, operasyonel görevler' },
						] as role}
							<button
								type="button"
								onclick={() => (scope.role = role.id)}
								class={[
									'flex-1 px-3 py-2.5 rounded-xl border text-left transition-colors',
									scope.role === role.id
										? 'bg-primary/5 border-primary/40 text-primary'
										: 'bg-background border-border text-muted-foreground hover:border-primary/30'
								].join(' ')}
							>
								<div class="text-sm font-semibold">{role.label}</div>
								<div class="text-xs mt-0.5 opacity-70">{role.desc}</div>
							</button>
						{/each}
					</div>
				</div>
			</div>

			<!-- Work Guide -->
			<div class="rounded-xl border bg-card p-6 space-y-4">
				<div>
					<h2 class="font-semibold">Work Guide</h2>
					<p class="text-sm text-muted-foreground mt-0.5">
						Bu kullanıcının yaptığı her ajan etkileşimine otomatik eklenen kurallar ve kaideler.
						Markdown formatında yazılır; ajanlara sistem bağlamı olarak iletilir.
					</p>
				</div>

				<!-- Quick suggestions -->
				<div class="space-y-2">
					<div class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Hızlı Ekle</div>
					<div class="flex flex-wrap gap-1.5">
						{#each GUIDE_SUGGESTIONS as s}
							<button
								type="button"
								onclick={() => addSuggestion(s)}
								class={[
									'px-2.5 py-1 rounded-full border text-xs transition-colors',
									guide.includes(s)
										? 'bg-muted border-border text-muted-foreground cursor-default'
										: 'bg-background border-dashed border-border text-muted-foreground hover:border-primary hover:text-primary'
								].join(' ')}
								disabled={guide.includes(s)}
							>
								{guide.includes(s) ? '✓ ' : '+ '}{s}
							</button>
						{/each}
					</div>
				</div>

				<!-- Editor -->
				<div class="space-y-1.5">
					<textarea
						bind:value={guide}
						rows="16"
						class="w-full rounded-lg border border-input bg-muted/30 px-4 py-3 text-sm font-mono leading-relaxed resize-y focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
						spellcheck="false"
						placeholder="# Çalışma Rehberi&#10;&#10;## Yanıt Tercihleri&#10;- Her zaman Türkçe yanıt ver&#10;..."
					></textarea>
					<p class="text-xs text-muted-foreground">
						Markdown desteklenir. Bu içerik ajanlarla konuşurken sistem promptuna eklenir.
					</p>
				</div>

				<div class="flex items-center justify-end gap-3">
					{#if guideSaved}
						<span class="text-sm text-emerald-600 flex items-center gap-1.5">
							<CheckCircle2 class="w-4 h-4" /> Kaydedildi
						</span>
					{/if}
					<Button onclick={saveGuide}>
						<Save class="w-4 h-4" />
						Rehberi Kaydet
					</Button>
				</div>
			</div>

		</div>
	{/if}

</div>
