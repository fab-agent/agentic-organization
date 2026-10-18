---
sidebar_position: 10
---

# Değişiklik Talepleri

Ajanlara verilen yetenekler ve izinler şirketin riskini etkiler. Bu yüzden bir ajanın yapılandırması, yeteneği veya politikası **iki aşamalı onayla** değişir. Onay sonunda değişiklik uygulanır ve istenirse Git'e yazılır.

**Nerede:** **Değişiklikler** (Bölüm yöneticisi ve üstü).

## Ne için kullanılır?

| Tür | Ne değişir |
|---|---|
| **Ajan yapılandırması** (`agent_config`) | Ad, ünvan, departman, model, durum, sorumlu, ajana özel yetenekler |
| **Yetenek** (`skill`) | Şirket yeteneğinin içeriği veya ayarı |
| **Politika** (`policy`) | Bir politikanın metni |

Talep şu yollarla açılır: **Ajanlar** sayfasındaki **Değişiklik Talebi** düğmesi (başlık, tür ve önerilen değerler girilir); **Yetenekler** ve **Politikalar** sayfalarında bir kaydı düzenleyip **Onaya Gönder**'e basmak.

## Onay akışı

```
submitted ──► dept_head_approved ──► committed
   │                  │
   └──────► rejected ◄┘
```

| Aşama | Kim | Ne yapar |
|---|---|---|
| 1. Bölüm onayı | Bölüm yöneticisi veya üstü | **Bölüm Onayla** veya **Reddet** (isteğe bağlı not) |
| 2. Son onay | Yönetici veya kurucu | **Admin Onayla & Commit Et** veya **Reddet** |

Sayfada durum filtreleri vardır: Tümü, Bekliyor, Bölüm Onaylandı, Commit Edildi, Reddedildi. Bir talebi açınca onay geçmişini, notları ve önerilen değişikliği görürsünüz.

## Son onayda ne olur?

1. Şirket için bir **Git bağlantısı** tanımlıysa, değişiklik ilgili dosyaya commit edilir:
   - Ajan yapılandırması → `agents/<slug>/agent.yaml`
   - Yetenekler → `agents/<slug>/skills.yaml`
   - Politika → `agents/<slug>/policy.yaml`

   Commit mesajı talep başlığını, türünü ve talep kimliğini taşır; commit bağlantısı talebe yazılır.
2. Commit başarılıysa değişiklik **veritabanına uygulanır** ve talep **committed** olur.
3. Git bağlantısı **yoksa** değişiklik doğrudan uygulanır ve talep yine **committed** olur.
4. Commit **başarısız** olursa onay kaydedilir ama değişiklik uygulanmaz; hata talebin notuna yazılır. Sorunu giderip yeniden denemeniz gerekir (bkz. [Ayarlar → Git](/guide/settings#git-entegrasyonu)).

:::info Desteklenen Git sistemi: GitHub
Değişiklik talebi commit'i şu an yalnızca **GitHub** için çalışır. Yerel bir git sistemiyle şirket politikalarını kod deposu gibi yönetmek **planlanan** bir çalışmadır, henüz yoktur; bkz. [Geliştirici Notları](/developer-notes/overview).
:::
