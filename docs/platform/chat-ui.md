---
sidebar_position: 2
---

# İşler Sayfası — Ajan ile Konuşma

**İşler** (`/chat`) sayfası, platformdaki ajanlarla gerçek zamanlı sohbet etmeyi sağlar. Sol panel oturumları, orta alan mesajları, sağ panel ise aktif ajanın bilgilerini gösterir.

---

## Sayfa Düzeni

```
┌─────────────────────────────────────────────────────────────────┐
│  Oturumlar          │  Sohbet Alanı              │  Ajan Bilgisi │
│  ─────────────────  │  ──────────────────────    │  ──────────── │
│  [+ Yeni Oturum]   │                            │  Model        │
│                     │  [Asistan mesajı]          │  Yetenekler   │
│  Oturum 1           │  [Kullanıcı mesajı]        │  Departman    │
│  Oturum 2           │  [Araç çağrısı]            │               │
│  Oturum 3           │  [Araç sonucu]             │               │
│                     │  ──────────────────────    │               │
│                     │  [Mesaj giriş alanı]       │               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Yeni Oturum Başlatma

1. Sol panelde **"Yeni Oturum"** butonuna bas veya `+` ikonuna tıkla.
2. Ajan seçici açılır — şirketin tüm aktif ajanları listelenir.
3. Bir ajan seç.
4. İlk mesajını yaz ve gönder.

:::tip URL parametresi
Belirli bir ajanla doğrudan sohbet başlatmak için URL'e `?agent=<agent_id>` ekleyebilirsin: `/chat?agent=abc123`
:::

---

## Mesaj Gönderme

- Metin kutusuna mesajını yaz.
- **Enter** tuşu → gönder. **Shift+Enter** → satır sonu.
- Mesaj gönderilirken giriş alanı ve gönder butonu devre dışı kalır.
- **Durdur** butonuna basarak çalışan bir yanıt iptal edilebilir.

---

## Gerçek Zamanlı Akış

Ajan yanıt verirken mesaj harfler halinde görünür (streaming). Ajan bir araç kullanmaya karar verdiğinde:

1. Araç çağrısı kutusu belirir (araç adı + argümanlar)
2. Araç çalışır, sonuç kutusu eklenir
3. Ajan sonucu analiz edip metin yanıtını tamamlar

Araç çağrısı örneği (arayüzde göründüğü haliyle):

```
🔧 web_search
   query: "Q2 2026 e-ticaret büyüme oranı"

✅ web_search
   Q2 2026 Türkiye e-ticaret pazarı %22 büyüdü...
```

---

## Ajan Bilgi Paneli

Sağ panelde aktif ajanın şu bilgileri görüntülenir:

| Bilgi | Açıklama |
|---|---|
| **Model** | Kullanılan AI modeli (ör. `gemini-2.0-flash`) |
| **Yetenekler** | Aktif skill listesi, her biri `builtin` / `mcp` / `http` / `function` badge'iyle |
| **Departman** | Ajanın bağlı olduğu departman |

Panel kapatılabilir; yeniden açmak için sağ üstteki bilgi ikonuna tıklanır.

---

## Oturum Geçmişi

Kapatılmamış (`active`) tüm oturumlar sol panelde listelenir. Bir oturuma tıklanınca tüm mesaj geçmişi yüklenir. `DELETE /sessions/{id}` ile oturum kapatılır.

---

## Şirket Değişikliği

Aktif şirket değiştirildiğinde:
- Tüm oturum ve mesaj verileri temizlenir
- Ajan listesi yeni şirkete göre yeniden yüklenir
- Aktif oturum sıfırlanır

Bu davranış `$effect` kullanılarak uygulanır:

```svelte
$effect(() => {
  if (companyStore.active) {
    activeSession = null;
    messages = [];
    selectedAgent = null;
    loadAgents();
    loadSessions();
  }
});
```

---

## Frontend API — streamMessage

`src/lib/api/sessions.ts` içindeki `streamMessage()` fonksiyonu `fetch` + `ReadableStream` ile SSE'yi tüketir ve bir async generator döndürür:

```typescript
for await (const event of streamMessage(sessionId, userInput, abortSignal)) {
  switch (event.type) {
    case 'text':        // akış metnini biriktir
    case 'tool_call':   // araç çağrısı kutusu göster
    case 'tool_result': // araç sonucu göster
    case 'done':        // mesajı tamamla, DB'deki message_id al
    case 'error':       // hata göster
    case 'stream_end':  // akışı kapat
  }
}
```

`AbortController` ile devam eden akış iptal edilebilir.

---

## İlgili Belgeler

- [Agent Runtime](./agent-runtime.md)
- [Mesaj İçeriği Bileşeni](./message-rendering.md)
- [A2A Delegasyon](./a2a-delegation.md)
