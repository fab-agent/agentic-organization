---
sidebar_position: 1
---

# Herdr İstemcisi: Genel Bakış

> ADR-0026 (önerildi) · Durum: sunucu ve `3pa` tarafı kodda; **gerçek bir Herdr penceresinde uçtan uca denenmedi**

Platform, günlük istemci olarak [Herdr](https://github.com/herdrdev) uygulamasını (masaüstü penceresi) ve
çekirdeğini (terminalleri ve ajanları çalışır tutan katman) kullanacak biçimde genişletiliyor. Sunucu, kişiye
**rolüne göre bir yerleşim (layout) ve mod paketi** verir; `3pa` bu paketi imzasını doğrulayarak kullanıcının
Herdr klasörüne kurar. Opencode tabanlı [iş istasyonu](/workstation/overview) çalışmaya devam eder; bu yeni yol onun
yerine geçmez, yanına eklenir.

## Üç parça

| Parça | Ne yapar | Sayfa |
|---|---|---|
| **İmzalı çalışma alanı** | Sunucu `GET /me/workspace` ile role göre yerleşim + mod listesini imzalı verir; `3pa workspace` komutları kurar, doğrular, sunucuya sayı raporu gönderir | [Çalışma alanı](./workspace.md) |
| **Kurulum** | Linux/macOS/Windows kullanıcı kurulumu, imzalı sürüm zinciri, MDM'den bağımsız dağıtım sözleşmesi | [Kurulum ve dağıtım](./install.md) |
| **İzleme** | Şirket bazında tek bakış: servis, denetim, gateway, değerlendirme, imza anahtarı, oturumlar, istemciler | [İzleme](./monitoring.md) |

## Güvenlik modeli, kısaca

- **Herdr modları kısıtsız koddur.** Herdr'in kendi belgelerine göre modlar kullanıcının erişimiyle çalışır; izin
  modeli yok, yerleşim veya mod imzası yok. Bu yüzden *neyin kullanıcının klasörüne yazılacağını* tamamen istemci
  (`3pa`) belirler; `3pa` yalnızca çevrimdışı **kök anahtarın** onayladığı paketi kurar.
- **Kök anahtar çevrimdışıdır.** Sunucuda yalnızca kök tarafından imzalanmış, süreli bir *imza sertifikası* ve
  anahtarı bulunur. Çalınan bir sunucu anahtarı iptal listesiyle (CRL) devre dışı bırakılır; adımlar
  [kurtarma runbook'unda](https://github.com/fab-agent/agentic-organization/blob/main/docs/runbooks/workspace-signing-key-recovery.md).
- **Profil seçimi yetki değildir.** Rol yalnızca kişiye hangi dosyaların sunulacağını seçer; her arka uç çağrısı
  kişiyi, şirketi ve rolü kendisi yeniden denetler.
- **Sunucuda politika kapısı kapalı-başarısızdır.** Politika altyapısı hata verirse işlem engellenir; ayrıntı
  [Politika motoru](/workstation/policy-engine) sayfasında.

## Bilinen sınırlar

- Yerleşimi açık Herdr penceresinde değiştirme (`layout.switch`) Herdr'in kaynak kodundan okunarak yazıldı;
  **çalışan bir pencerede denenmedi.**
- Windows'ta Herdr uygulama klasörünün varsayılanı (`%APPDATA%\herdr-app`) bir **tahmindir**; `--app-home` ile
  geçersiz kılınır.
- Windows ikilileri ve kurucu **Authenticode ile imzalı değil**; MSI ve PATH yönetimi yok.
- Herdr'in kendi otomatik güncellemesi için karar henüz yok (ADR-0026 madde 7).
- Çalışma alanı rolleri kullanıcının *kendi bilgisayarında* yaptıklarını (kendi API anahtarları, işletim sistemi
  düzeyi) engelleyemez; bunun için işletim sistemi/ağ çıkış politikası gerekir.
