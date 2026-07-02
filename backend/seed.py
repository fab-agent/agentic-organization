"""
Seed data — runs once on startup if DB is empty.
"""
import json
from sqlmodel import select
from database import get_session
from models import Company, Department, Personnel, AgentConfig, Skill


def run_seed() -> None:
    with get_session() as session:
        if session.exec(select(Department)).first():
            return  # already seeded

        # ── Companies ─────────────────────────────────────────────────────────
        company1 = Company(
            name="Fabrika Yazılım",
            slug="fabrika-yazilim",
            sector="Software",
            website="https://fab.limited",
        )
        company2 = Company(
            name="Demo Corp",
            slug="demo-corp",
            sector="Technology",
            website="https://democorp.example.com",
        )
        session.add(company1)
        session.add(company2)
        session.flush()

        # ── Departments ────────────────────────────────────────────────────────
        depts = [
            Department(
                company_id=company1.id,
                name="Yazılım Geliştirme",
                slug="yazilim-gelistirme",
                description="Ürün ve platform geliştirme, code review, deployment ve teknik altyapı yönetimi",
                goals=(
                    "Q2 sonuna kadar CI/CD pipeline tam otomasyonunu tamamlamak\n"
                    "Kod kalitesi metriklerini %90 üzerinde tutmak\n"
                    "Deployment frekansını haftada 3x'e çıkarmak\n"
                    "Teknik borç backlog'unu Q3'e kadar %30 azaltmak\n"
                    "Yeni geliştirici onboarding süresini 2 güne indirmek"
                ),
                policies_json=json.dumps([
                    "Yazılım Kalite Politikası",
                    "Code Review SLA (max 4 saat)",
                    "Güvenlik Tarama Politikası",
                    "Deployment Onay Politikası",
                    "Branch Yönetim Politikası",
                    "Bağımlılık Güncelleme Politikası",
                ]),
                status="Active",
            ),
            Department(
                company_id=company1.id,
                name="Kalite Güvence",
                slug="kalite-guvence",
                description="Test otomasyonu, bug tracking, regression yönetimi ve kullanıcı kabul testleri",
                goals=(
                    "Test coverage oranını %85 üzerinde tutmak\n"
                    "Regression bug çözüm süresi < 24 saat\n"
                    "Her sprint için minimum %95 test pass rate\n"
                    "Kritik yol senaryolarını tamamen otomatize etmek\n"
                    "Prod'a sıfır kritik bug geçişini hedeflemek"
                ),
                policies_json=json.dumps([
                    "QA Kabul Kriterleri Politikası",
                    "Test Coverage SLA (%85 minimum)",
                    "Bug Triage ve Önceliklendirme Politikası",
                    "Regression Test Politikası",
                ]),
                status="Active",
            ),
            Department(
                company_id=company1.id,
                name="Pazarlama & Büyüme",
                slug="pazarlama",
                description="İçerik üretimi, SEO, sosyal medya, kampanya yönetimi ve büyüme analitiği",
                goals=(
                    "Organik web trafiğini aylık %20 büyütmek\n"
                    "İçerik takvimi haftalık doluluk oranını %95'te tutmak\n"
                    "Lead başına edinim maliyetini (CAC) %15 düşürmek\n"
                    "Email open rate'i %28 üzerine çıkarmak\n"
                    "Q3'e kadar 3 yeni kanal denemesi yapmak"
                ),
                policies_json=json.dumps([
                    "İçerik Yayın Politikası",
                    "Marka Kimliği ve Ton Politikası",
                    "KVKK Uyumluluk ve Veri Gizliliği",
                    "Sosyal Medya Kullanım Politikası",
                    "Analitik Veri Erişim Politikası",
                ]),
                status="Active",
            ),
            Department(
                company_id=company1.id,
                name="Finans & Operasyon",
                slug="finans",
                description="Finansal raporlama, bütçe yönetimi, nakit akışı takibi ve operasyonel süreçler",
                goals=(
                    "Aylık finansal raporları 3. iş günü teslim etmek\n"
                    "Nakit akışı tahmininde ±%5 hata payında kalmak\n"
                    "Tüm vergi yükümlülüklerini zamanında yerine getirmek\n"
                    "Operasyonel giderleri bütçenin %95'i ile sınırlı tutmak\n"
                    "Fatura tahsilat süresini ortalama 20 güne indirmek"
                ),
                policies_json=json.dumps([
                    "Finansal Onay ve Yetkilendirme Politikası",
                    "Harcama Politikası (limitlere göre onay seviyeleri)",
                    "Uyumluluk ve Denetim Politikası",
                    "Veri Güvenliği ve Erişim Politikası",
                    "Faturalandırma ve Tahsilat Politikası",
                ]),
                status="Active",
            ),
            Department(
                company_id=company1.id,
                name="İnsan Kaynakları",
                slug="insan-kaynaklari",
                description="İşe alım, onboarding, performans yönetimi, çalışan deneyimi ve organizasyonel gelişim",
                goals=(
                    "Açık pozisyonları ortalama 21 günde kapatmak\n"
                    "Çalışan memnuniyet skorunu 4.2/5 üzerinde tutmak\n"
                    "Yıllık turnover oranını %15 altında tutmak\n"
                    "Tüm çalışanlar için kişisel gelişim planı oluşturmak\n"
                    "Onboarding NPS'ini 50 üzerine çıkarmak"
                ),
                policies_json=json.dumps([
                    "İşe Alım ve Seçim Politikası",
                    "Uzaktan Çalışma ve Hibrit Çalışma Politikası",
                    "Performans Değerlendirme Politikası",
                    "Eşit Fırsat ve Çeşitlilik Politikası",
                    "Disiplin ve Şikayet Süreci Politikası",
                ]),
                status="Active",
            ),
            Department(
                company_id=company1.id,
                name="Müşteri Başarısı",
                slug="musteri-basarisi",
                description="Müşteri onboarding, destek, başarı yönetimi ve churn azaltma operasyonları",
                goals=(
                    "Net Promoter Score (NPS) 60 üzerinde tutmak\n"
                    "Müşteri destek ilk yanıt süresini < 2 saate indirmek\n"
                    "Aylık churn oranını %1.5 altında tutmak\n"
                    "Onboarding tamamlanma oranını %90 üzerine çıkarmak\n"
                    "Upsell oranını %20'ye çıkarmak"
                ),
                policies_json=json.dumps([
                    "Müşteri Destek SLA Politikası",
                    "Veri Gizliliği ve Paylaşım Politikası",
                    "Eskalasyon Prosedürü Politikası",
                    "Müşteri Geri Bildirim Yönetim Politikası",
                ]),
                status="Active",
            ),
        ]
        for d in depts:
            session.add(d)
        session.flush()

        dm = {d.slug: d.id for d in depts}

        # ── Human Personnel (Company 1) ────────────────────────────────────────
        humans = [
            Personnel(name="Kuntay Kunt",  slug="kuntay-kunt",  title="CEO & Co-Founder",      role="CEO",                   type="human", company_id=company1.id, department_id=None),
            Personnel(name="Zeynep Çelik", slug="zeynep-celik", title="COO & Co-Founder",      role="COO",                   type="human", company_id=company1.id, department_id=None),
            Personnel(name="Ahmet Şahin",  slug="ahmet-sahin",  title="CTO",                   role="CTO",                   type="human", company_id=company1.id, department_id=dm["yazilim-gelistirme"]),
            Personnel(name="Elif Yıldız",  slug="elif-yildiz",  title="Engineering Lead",      role="Engineering Lead",      type="human", company_id=company1.id, department_id=dm["yazilim-gelistirme"]),
            Personnel(name="Burak Demir",  slug="burak-demir",  title="QA Lead",               role="QA Lead",               type="human", company_id=company1.id, department_id=dm["kalite-guvence"]),
            Personnel(name="Selin Kaya",   slug="selin-kaya",   title="CMO",                   role="CMO",                   type="human", company_id=company1.id, department_id=dm["pazarlama"]),
            Personnel(name="Ozan Yılmaz",  slug="ozan-yilmaz",  title="Growth Manager",        role="Growth Manager",        type="human", company_id=company1.id, department_id=dm["pazarlama"]),
            Personnel(name="Mert Arslan",  slug="mert-arslan",  title="CFO",                   role="CFO",                   type="human", company_id=company1.id, department_id=dm["finans"]),
            Personnel(name="Ayşe Kara",    slug="ayse-kara",    title="HR Manager",            role="HR Manager",            type="human", company_id=company1.id, department_id=dm["insan-kaynaklari"]),
            Personnel(name="Deniz Öztürk", slug="deniz-ozturk", title="CS Lead",               role="Customer Success Lead", type="human", company_id=company1.id, department_id=dm["musteri-basarisi"]),
        ]
        for h in humans:
            session.add(h)
        session.flush()

        hm = {h.slug: h.id for h in humans}

        humans[1].manager_id = hm["kuntay-kunt"]
        humans[2].manager_id = hm["kuntay-kunt"]
        humans[3].manager_id = hm["ahmet-sahin"]
        humans[4].manager_id = hm["ahmet-sahin"]
        humans[5].manager_id = hm["kuntay-kunt"]
        humans[6].manager_id = hm["selin-kaya"]
        humans[7].manager_id = hm["zeynep-celik"]
        humans[8].manager_id = hm["zeynep-celik"]
        humans[9].manager_id = hm["zeynep-celik"]
        session.flush()

        # ── Agents ────────────────────────────────────────────────────────────
        agent_defs = [
            dict(name="CodeGuard",   slug="codeguard",   title="Code Review Agent",          dept="yazilim-gelistirme", manager="elif-yildiz",
                 model="claude-sonnet-4-6", version="4.6",     status="active", responsible="elif-yildiz",
                 skills=[("Code Review","2.1","PR inceleme, best practice ve güvenlik açığı taraması"),
                         ("TypeScript","5.x","Tip güvenliği analizi ve refactor önerileri"),
                         ("Git Workflow","1.0","Branch stratejisi ve commit standardizasyonu"),
                         ("Security Scan","1.2","OWASP top-10 ve dependency vulnerability tespiti")]),
            dict(name="DeployBot",   slug="deploybot",   title="Deploy & CI/CD Agent",       dept="yazilim-gelistirme", manager="elif-yildiz",
                 model="gpt-4o",           version="2024-11",  status="active", responsible="elif-yildiz",
                 skills=[("Docker","24.x","Container build, push ve orchestration"),
                         ("GitHub Actions","3.x","CI/CD pipeline kurulum ve optimizasyon"),
                         ("Monitoring","1.2","Deploy sonrası sağlık kontrolü ve rollback"),
                         ("Infrastructure","1.0","Terraform ve cloud resource yönetimi")]),
            dict(name="TestMind",    slug="testmind",    title="QA Automation Agent",        dept="kalite-guvence",    manager="burak-demir",
                 model="claude-sonnet-4-6", version="4.6",     status="active", responsible="burak-demir",
                 skills=[("Test Generation","1.3","Playwright ve Vitest ile otomatik test"),
                         ("Bug Triage","1.0","Hata önceliklendirme ve regression analizi"),
                         ("Coverage Report","1.1","Test coverage raporlama ve boşluk tespiti")]),
            dict(name="ContentFlow", slug="contentflow", title="Content & SEO Agent",        dept="pazarlama",         manager="selin-kaya",
                 model="claude-sonnet-4-6", version="4.6",     status="active", responsible="selin-kaya",
                 skills=[("Copywriting","2.0","Blog, sosyal medya ve landing page içerik üretimi"),
                         ("SEO","1.4","Anahtar kelime araştırması ve on-page optimizasyon"),
                         ("Social Media","1.1","Çoklu platform içerik takvimi yönetimi"),
                         ("Brand Voice","1.0","Marka kimliğine uygun ton standardizasyonu")]),
            dict(name="DataLens",    slug="datalens",    title="Growth Analytics Agent",     dept="pazarlama",         manager="ozan-yilmaz",
                 model="gemini-2.5-pro",   version="2025-05",  status="draft",  responsible="ozan-yilmaz",
                 skills=[("Data Analysis","1.0","GA4, Mixpanel ve SQL tabanlı raporlama"),
                         ("Visualization","0.9","Looker Studio ve custom dashboard"),
                         ("A/B Testing","0.8","Deney tasarımı ve istatistiksel anlamlılık")]),
            dict(name="LedgerAI",    slug="ledgerai",    title="Finance & Reporting Agent",  dept="finans",            manager="mert-arslan",
                 model="gpt-4o",           version="2024-11",  status="active", responsible="mert-arslan",
                 skills=[("Forecasting","1.2","Nakit akışı tahmini ve bütçe sapma tespiti"),
                         ("Reporting","2.0","Aylık/çeyreklik finansal rapor otomasyonu"),
                         ("Compliance","1.0","Vergi yükümlülükleri kontrol ve uyarı"),
                         ("Reconciliation","1.0","Banka ekstresi mutabakatı ve fatura eşleştirme")]),
            dict(name="TalentScout", slug="talentscout", title="Recruitment Assistant Agent",dept="insan-kaynaklari",  manager="ayse-kara",
                 model="claude-sonnet-4-6", version="4.6",     status="active", responsible="ayse-kara",
                 skills=[("CV Screening","1.0","CV analizi ve kriterlere göre skorlama"),
                         ("JD Writing","1.1","İş ilanı yazımı ve kanal önerisi"),
                         ("Interview Prep","0.9","Teknik ve yetkinlik bazlı soru seti hazırlama")]),
            dict(name="SupportBot",  slug="supportbot",  title="Customer Support Agent",     dept="musteri-basarisi",  manager="deniz-ozturk",
                 model="claude-sonnet-4-6", version="4.6",     status="active", responsible="deniz-ozturk",
                 skills=[("Ticket Triage","1.2","Destek talebi önceliklendirme ve yönlendirme"),
                         ("FAQ Generation","1.0","Geçmiş biletlerden SSS ve knowledge base"),
                         ("Churn Detection","0.9","Risk sinyali analizi ve erken uyarı sistemi")]),
            dict(name="OnboardAI",   slug="onboardai",   title="Customer Onboarding Agent",  dept="musteri-basarisi",  manager="deniz-ozturk",
                 model="gemini-2.5-pro",   version="2025-05",  status="draft",  responsible="deniz-ozturk",
                 skills=[("Onboarding Flow","0.8","Müşteri segmentine özel onboarding planı"),
                         ("Progress Track","0.7","Milestone takibi ve gecikme müdahalesi")]),
        ]

        for ad in agent_defs:
            p = Personnel(
                name=ad["name"], slug=ad["slug"], title=ad["title"],
                type="agent",
                company_id=company1.id,
                department_id=dm[ad["dept"]],
                manager_id=hm[ad["manager"]],
            )
            session.add(p)
            session.flush()

            cfg = AgentConfig(
                personnel_id=p.id,
                model=ad["model"],
                model_version=ad["version"],
                status=ad["status"],
                responsible_id=hm[ad["responsible"]],
            )
            session.add(cfg)
            session.flush()

            for name, version, description in ad["skills"]:
                session.add(Skill(agent_id=cfg.id, name=name, version=version, description=description))

        # ── Demo Corp (Company 2) ─────────────────────────────────────────────
        demo_dept = Department(
            company_id=company2.id,
            name="Engineering",
            slug="engineering",
            description="Product engineering and infrastructure",
            goals="Ship v1.0 by Q3\nMaintain 99.9% uptime",
            policies_json=json.dumps(["Code Review Policy", "Deployment Policy"]),
            status="Active",
        )
        session.add(demo_dept)
        session.flush()

        demo_ceo = Personnel(
            name="Jane Smith", slug="jane-smith", title="CEO", role="CEO",
            type="human", company_id=company2.id, department_id=None,
        )
        session.add(demo_ceo)
        session.flush()

        demo_eng = Personnel(
            name="Tom Lee", slug="tom-lee", title="Engineering Lead", role="Engineering Lead",
            type="human", company_id=company2.id, department_id=demo_dept.id,
            manager_id=demo_ceo.id,
        )
        session.add(demo_eng)
        session.flush()

        demo_agent_p = Personnel(
            name="AutoDev", slug="autodev", title="Development Agent", type="agent",
            company_id=company2.id, department_id=demo_dept.id, manager_id=demo_eng.id,
        )
        session.add(demo_agent_p)
        session.flush()

        demo_cfg = AgentConfig(
            personnel_id=demo_agent_p.id,
            model="claude-sonnet-4-6",
            model_version="4.6",
            status="draft",
            responsible_id=demo_eng.id,
        )
        session.add(demo_cfg)
        session.flush()
        session.add(Skill(agent_id=demo_cfg.id, name="Code Generation", version="1.0", description="Automated code scaffolding"))

        session.commit()
        print("✅ Seed: 2 companies, 7 departments, 13 humans, 10 agents")
