---
sidebar_position: 1
---

# Ajan Yürütme Katmanı — Genel Bakış

Platformun web arayüzü, ajanları **tanımlamak** için kullanılır: kim hangi
departmanda, hangi model, hangi skill, hangi politika. **Ajan Yürütme Katmanı**
(kod adı *Agentic OS*) ise geliştirici personaların bu tanımlarla gerçek işi
yapmasını sağlar — kendi iş istasyonlarında, kod tabanının içinde.

Geliştirici persona, iş istasyonunda [**opencode**](https://opencode.ai) çalıştırır.
Tüm model trafiği merkezî bir **gateway**'den geçer, her araç çağrısı
**çalıştırılabilir politikalarla** değerlendirilir ve her eylem **değiştirilemez
bir denetim zincirine** yazılır. Web arayüzü bu katmandan habersizdir; katman
opsiyoneldir ve onun yanında çalışır.

---

## Neden

| Sorun | Yürütme Katmanının cevabı |
|---|---|
| Ajanlar ham API anahtarlarını görüyor | Gateway — persona token'ı ile bağlanır, upstream anahtarı hiç görülmez |
| "Ajan ne yaptı?" sorusuna kanıt yok | Hash-zincirli denetim + harici çıpalama |
| Politikalar yalnızca sistem prompt'unda öneri | Araç çağrısından önce çalışan fail-closed politika motoru |
| Yerel ajan sınırsız komut çalıştırabilir | Zorunlu yerel sandbox + egress allowlist |
| Prompt injection ile araç kötüye kullanımı | Katmanlı injection savunması (köken izleme → egress → imzalı komut kanalı) |
| Uzun ömürlü kimlik bilgisi sızıntısı | ~60 dakikalık access token + iptal + otomatik bayat-oturum temizliği |

---

## Bileşenler

```
  ┌─────────────────────── İş istasyonu ───────────────────────┐
  │                                                            │
  │   3pa CLI ──► opencode  (yönetilen sandbox konteyneri)     │
  │                │  ▲         │                               │
  │        plugin  │  │ base-prompt.md (guardrail)             │
  │                ▼  │         ▼                               │
  │        egress proxy (allowlist)  ──────────────────────┐    │
  └───────────────────────────────────────────────────────│────┘
                                                          │
                       HTTPS (persona bearer token)       │
                                                          ▼
  ┌──────────────────────── Platform backend ──────────────────┐
  │                                                            │
  │   /v1/*          LLM Gateway ──► şirketin upstream'i        │
  │   /policy/decide Politika Motoru (off|dry_run|enforce)     │
  │   /workstation/* heartbeat · token · imzalı komut kanalı   │
  │   /audit/*       Denetim Zinciri ──► S3 Object Lock çıpası │
  │   /.well-known/opencode   imzalı yönetilen yapılandırma    │
  │   /mcp           persona skill'leri (JSON-RPC)             │
  └────────────────────────────────────────────────────────────┘
```

| Bileşen | Belge |
|---|---|
| Merkezî LLM Gateway | [llm-gateway](./llm-gateway.md) |
| Çalıştırılabilir Politika Motoru | [policy-engine](./policy-engine.md) |
| Değiştirilemez Denetim Zinciri | [audit-chain](./audit-chain.md) |
| Persona Kimliği ve Token'lar | [identity](./identity.md) |
| `3pa` İş İstasyonu CLI | [cli](./cli.md) |
| İzole Çalıştırma Ortamı (sandbox) | [sandbox](./sandbox.md) |
| Prompt Injection Savunması | [injection-defense](./injection-defense.md) |
| Yönetilen opencode Yapılandırması | [managed-config](./managed-config.md) |

---

## Tasarım ilkeleri

- **Fail-closed.** Politika değerlendirmesi, token doğrulama ve iptal kontrolü —
  hata durumunda hepsi engeller, geçirmez.
- **Varsayılanlar serbest.** Gateway kotaları, politika modu (`dry_run`),
  önem skorlaması — hiçbiri açıkça yapılandırılmadan kısıtlamaz. Katman önce
  gözlemlenir, sonra zorlanır.
- **Web arayüzüne dokunulmaz.** Yürütme katmanı ayrı router'lar, ayrı tablolar,
  ayrı CI iş akışlarıdır.
- **Karar = kod.** Her mimari karar `docs/adr/` altında bir ADR'dir
  (ADR-0001 … ADR-0013).
