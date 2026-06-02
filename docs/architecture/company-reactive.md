---
sidebar_position: 5
---

# Şirkete Reaktif Veri Yükleme

Platformda birden fazla şirket yönetilebilir. Kullanıcı aktif şirketi değiştirdiğinde tüm sayfaların verilerini o şirkete göre yeniden yüklemesi gerekir. Bu davranış tutarlı bir Svelte 5 `$effect` deseniyle uygulanmıştır.

---

## Sorun

SvelteKit sayfaları `onMount` içinde veri yükler. Ancak `onMount` yalnızca sayfa ilk açıldığında çalışır; kullanıcı şirket değiştirdiğinde `onMount` yeniden tetiklenmez. Dolayısıyla yalnızca `onMount` kullanan sayfalar eski şirketin verisini göstermeye devam eder.

---

## Çözüm: onMount + $effect Deseni

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { companyStore } from '$lib/stores/company.svelte';

  let data = $state([]);

  // İlk yükleme
  onMount(load);

  // Şirket değişikliğinde yeniden yükle
  $effect(() => {
    if (companyStore.active) load();
  });

  async function load() {
    data = await api.list({ company_id: companyStore.active?.id });
  }
</script>
```

`onMount` ilk render için, `$effect` ise `companyStore.active` değiştiği her an için çalışır. `company_id` filtresi API çağrısına eklenerek yalnızca o şirkete ait veriler döner.

---

## Neden İkisi Birden?

| Durum | `onMount` | `$effect` |
|---|---|---|
| Sayfa ilk açıldı | Çalışır | Çalışır (companyStore zaten set) |
| Şirket değişti | Çalışmaz | Çalışır |
| Sayfa zaten açıkken şirket değişti | Çalışmaz | Çalışır |

Yalnızca `$effect` kullanılsaydı SSR sırasında `companyStore.active` henüz yüklenmemiş olabilir. Yalnızca `onMount` kullanılsaydı şirket değişikliği yakalanmazdı. İkisi birlikte tüm senaryoları kapsar.

:::note $effect ve reaktivite
Svelte 5 rune sistemi `$effect` bloğu içinde okunan herhangi bir `$state` değişkeninin değişimini izler. `companyStore.active` bir `$state` nesnesi olduğundan değiştiği anda effect yeniden çalışır.
:::

---

## Bu Deseni Kullanan Sayfalar

| Sayfa | Rota | Yüklenen Veri |
|---|---|---|
| Yapı | `/` | Departman + personel özet |
| Bölümler | `/departments` | Departman listesi |
| İnsanlar | `/personnel` | Personel listesi |
| Ajanlar | `/agents` | Ajan listesi |
| Org Haritası | `/org-chart` | Hiyerarşik ağaç verisi |
| İşler | `/chat` | Oturumlar + ajan listesi |
| Delegasyon | `/a2a` | A2A talep listesi |

Kenar çubuk bileşeni de bekleyen delegasyon sayısı için aynı deseni kullanır.

---

## Kenar Çubuk: Bekleyen Sayacı

Kenar çubuk (`+layout.svelte`) aşağıdaki şekilde delegasyon sayısını izler:

```svelte
let pendingCount = $state(0);

onMount(loadPendingCount);

$effect(() => {
  if (companyStore.active) loadPendingCount();
});

async function loadPendingCount() {
  const { count } = await a2aApi.pendingCount({
    company_id: companyStore.active?.id
  });
  pendingCount = count;
}
```

`pendingCount > 0` olduğunda:
- Menüdeki **Delegasyon** öğesinin yanında amber rozet görünür
- Şirket kartında amber pulse noktası belirir

---

## API Filtresi: company_id

Tüm liste endpoint'leri `company_id` query parametresini destekler. Parametre belirtilmezse tüm şirketlerin verisi döner (geliştirme/test amaçlı):

```bash
GET /personnel?company_id=<uuid>&type=agent
GET /departments?company_id=<uuid>
GET /sessions?personnel_id=<uuid>
GET /a2a/requests?company_id=<uuid>
GET /a2a/requests/pending-count?company_id=<uuid>
```

---

## Yeni Sayfa Yazarken

Platforma yeni bir sayfa eklendiğinde şu şablonu kullan:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { companyStore } from '$lib/stores/company.svelte';
  import { myApi } from '$lib/api/my-module';

  let items = $state([]);
  let loading = $state(true);

  onMount(load);
  $effect(() => { if (companyStore.active) load(); });

  async function load() {
    loading = true;
    try {
      items = await myApi.list({ company_id: companyStore.active?.id });
    } finally {
      loading = false;
    }
  }
</script>
```

Hiçbir sayfada şirket değişikliği sonrası manuel `window.location.reload()` veya sayfa yönlendirmesine gerek yoktur.

---

## İlgili Belgeler

- [3rdParty Agent Org Mimarisi](./3rdparty-agent-org.md)
- [İşler Sayfası](../platform/chat-ui.md)
- [A2A Delegasyon](../platform/a2a-delegation.md)
