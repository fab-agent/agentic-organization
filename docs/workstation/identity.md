---
sidebar_position: 5
---

# Persona Kimliği ve Token'lar

> ADR-0007 · `backend/api/workstation.py`, `backend/services/persona_revocation.py`,
> `backend/api/deps.py`, `backend/services/oidc.py`

Bir geliştirici persona iş istasyonunda çalışırken, platforma **kısa ömürlü**
bir kimlikle bağlanır. Uzun ömürlü bir API anahtarı iş istasyonunda tutulmaz;
sızarsa etkisi dakikalarla sınırlıdır ve anında iptal edilebilir.

---

## İki token

| Token | `typ` | Ömür | Kullanım |
|---|---|---|---|
| Access | `persona` | ~60 dk | Gateway ve `/workstation/*` çağrıları |
| Refresh | `persona_refresh` (`aud=refresh`) | ~12 sa | Yeni access token almak |

Her ikisinde de `jti` (benzersiz token kimliği) bulunur. `3pa login` çifti alır
ve `~/.config/3pa/session.json` içine yazar; `3pa refresh` access token'ı yeniler.

---

## Endpoint'ler

| Method | Yol | Kim |
|---|---|---|
| `GET`  | `/workstation/personas` | Sahip — yönetebildiği personalar |
| `POST` | `/workstation/persona-token` | Sahip — bir persona için token çifti |
| `POST` | `/workstation/persona-token/refresh` | Refresh token sahibi |
| `POST` | `/workstation/persona-token/revoke` | Sahip **veya** persona'nın kendisi |
| `POST` | `/workstation/oidc/exchange` | OIDC ID token → persona token (opsiyonel) |

---

## İptal — fail-closed

Her korunan istekte `api/deps.py` iptal kontrolü yapar. Kontrol **fail-closed**:
DB'ye ulaşılamazsa istek reddedilir.

| Mekanizma | Ne yapar |
|---|---|
| `RevokedToken` | Belirli bir `jti` kara listeye alınır |
| `PersonaTokenState` | Persona için bir **not-before** işareti — bu andan önce üretilmiş tüm token'lar geçersiz (toplu iptal) |

`revoke_jti()` tek token'ı, `revoke_all()` bir persona'nın tüm token'larını
iptal eder.

---

## Otomatik bakım

`revocation_maintenance` APScheduler işi:

- Uzun süredir heartbeat göndermeyen (**bayat**) oturumların token'larını
  otomatik iptal eder.
- Süresi çoktan dolmuş `RevokedToken` satırlarını temizler (tablo şişmesin).

---

## OIDC (opsiyonel)

`services/oidc.py` — kurumsal bir OIDC sağlayıcısının ID token'ını persona
token'ına çevirir (JWKS ile imza doğrulama). `oidc.enabled` olmadıkça **kapalı**;
tanımadığı bir kullanıcı için **otomatik hesap oluşturmaz**.

---

## Açık konular

- Sandbox içinde 60 dakikadan uzun süren çalıştırmalar için token rotasyonu.
- Cihaz kaydı — bilinen iş istasyonlarını bir cihaz kimliğiyle eşleme.
