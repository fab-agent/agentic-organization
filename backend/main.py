from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, create_engine, Session, select
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import os
import json

from models import Department, Personnel, AgentConfig, Skill

app = FastAPI(
    title="3rdParty Agent Organization API",
    version="0.2.0",
    description="Self-hosted agentic organization management platform"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def dept_to_dict(d: Department) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "slug": d.slug,
        "description": d.description,
        "goals": d.goals,
        "policies": d.policies(),
        "status": d.status,
        "created_at": d.created_at.isoformat(),
    }


@app.on_event("startup")
def on_startup():
    os.makedirs("data", exist_ok=True)
    SQLModel.metadata.create_all(engine)
    _seed()
    print("✅ Database ready")


def _seed():
    with Session(engine) as session:
        if session.exec(select(Department)).first():
            return  # already seeded

        # ── Departments ────────────────────────────────────────────────────────
        depts = [
            Department(
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

        # ── Human Personnel ────────────────────────────────────────────────────
        dept_map = {d.slug: d.id for d in depts}

        humans = [
            # C-Suite (no department)
            Personnel(name="Kuntay Kunt",      slug="kuntay-kunt",      title="CEO & Co-Founder",       role="CEO",                    type="human", department_id=None),
            Personnel(name="Zeynep Çelik",     slug="zeynep-celik",     title="COO & Co-Founder",       role="COO",                    type="human", department_id=None),
            # Tech
            Personnel(name="Ahmet Şahin",      slug="ahmet-sahin",      title="CTO",                    role="CTO",                    type="human", department_id=dept_map["yazilim-gelistirme"]),
            Personnel(name="Elif Yıldız",      slug="elif-yildiz",      title="Engineering Lead",       role="Engineering Lead",       type="human", department_id=dept_map["yazilim-gelistirme"]),
            Personnel(name="Burak Demir",      slug="burak-demir",      title="QA Lead",                role="QA Lead",                type="human", department_id=dept_map["kalite-guvence"]),
            # Marketing
            Personnel(name="Selin Kaya",       slug="selin-kaya",       title="CMO",                    role="CMO",                    type="human", department_id=dept_map["pazarlama"]),
            Personnel(name="Ozan Yılmaz",      slug="ozan-yilmaz",      title="Growth Manager",         role="Growth Manager",         type="human", department_id=dept_map["pazarlama"]),
            # Finance
            Personnel(name="Mert Arslan",      slug="mert-arslan",      title="CFO",                    role="CFO",                    type="human", department_id=dept_map["finans"]),
            # HR
            Personnel(name="Ayşe Kara",        slug="ayse-kara",        title="HR Manager",             role="HR Manager",             type="human", department_id=dept_map["insan-kaynaklari"]),
            # Customer Success
            Personnel(name="Deniz Öztürk",     slug="deniz-ozturk",     title="CS Lead",                role="Customer Success Lead",  type="human", department_id=dept_map["musteri-basarisi"]),
        ]
        for h in humans:
            session.add(h)
        session.flush()

        hm = {h.slug: h.id for h in humans}

        # Hierarchy
        humans[1].manager_id = hm["kuntay-kunt"]   # COO → CEO
        humans[2].manager_id = hm["kuntay-kunt"]   # CTO → CEO
        humans[3].manager_id = hm["ahmet-sahin"]   # Eng Lead → CTO
        humans[4].manager_id = hm["ahmet-sahin"]   # QA Lead → CTO
        humans[5].manager_id = hm["kuntay-kunt"]   # CMO → CEO
        humans[6].manager_id = hm["selin-kaya"]    # Growth Mgr → CMO
        humans[7].manager_id = hm["zeynep-celik"]  # CFO → COO
        humans[8].manager_id = hm["zeynep-celik"]  # HR Mgr → COO
        humans[9].manager_id = hm["zeynep-celik"]  # CS Lead → COO
        session.flush()

        # ── Agents ────────────────────────────────────────────────────────────
        agent_defs = [
            # Yazılım Geliştirme
            dict(
                name="CodeGuard", slug="codeguard", title="Code Review Agent",
                department_id=dept_map["yazilim-gelistirme"], manager_id=hm["elif-yildiz"],
                model="claude-sonnet-4", model_version="4.6", status="active", responsible_slug="elif-yildiz",
                skills=[
                    ("Code Review",   "2.1", "PR inceleme, best practice kontrolü, güvenlik açığı taraması"),
                    ("TypeScript",    "5.x", "Tip güvenliği analizi, interface tasarımı ve refactor önerileri"),
                    ("Git Workflow",  "1.0", "Branch stratejisi, commit mesajı standardizasyonu"),
                    ("Security Scan", "1.2", "OWASP top-10 kontrolü, dependency vulnerability tespiti"),
                ]
            ),
            dict(
                name="DeployBot", slug="deploybot", title="Deploy & CI/CD Agent",
                department_id=dept_map["yazilim-gelistirme"], manager_id=hm["elif-yildiz"],
                model="gpt-4o", model_version="2024-11", status="active", responsible_slug="elif-yildiz",
                skills=[
                    ("Docker",          "24.x", "Container build, push ve multi-stage orchestration"),
                    ("GitHub Actions",  "3.x",  "CI/CD pipeline kurulum, optimizasyon ve hata tespiti"),
                    ("Monitoring",      "1.2",  "Deploy sonrası sağlık kontrolü ve otomatik rollback kararı"),
                    ("Infrastructure",  "1.0",  "Terraform ve cloud resource yönetimi"),
                ]
            ),
            # Kalite Güvence
            dict(
                name="TestMind", slug="testmind", title="QA Automation Agent",
                department_id=dept_map["kalite-guvence"], manager_id=hm["burak-demir"],
                model="claude-sonnet-4", model_version="4.6", status="active", responsible_slug="burak-demir",
                skills=[
                    ("Test Generation", "1.3", "Playwright ve Vitest ile kapsamlı otomatik test yazımı"),
                    ("Bug Triage",      "1.0", "Hata önceliklendirme, etki analizi ve regression tespiti"),
                    ("Coverage Report", "1.1", "Test coverage raporu hazırlama ve eksik alanların tespiti"),
                ]
            ),
            # Pazarlama
            dict(
                name="ContentFlow", slug="contentflow", title="Content & SEO Agent",
                department_id=dept_map["pazarlama"], manager_id=hm["selin-kaya"],
                model="claude-sonnet-4", model_version="4.6", status="active", responsible_slug="selin-kaya",
                skills=[
                    ("Copywriting",   "2.0", "Blog, sosyal medya, landing page ve email içerik üretimi"),
                    ("SEO",           "1.4", "Anahtar kelime araştırması, on-page optimizasyon ve içerik stratejisi"),
                    ("Social Media",  "1.1", "Çoklu platform içerik takvimi planlama ve yayın yönetimi"),
                    ("Brand Voice",   "1.0", "Marka kimliğine uygun ton ve üslup standardizasyonu"),
                ]
            ),
            dict(
                name="DataLens", slug="datalens", title="Growth Analytics Agent",
                department_id=dept_map["pazarlama"], manager_id=hm["ozan-yilmaz"],
                model="gemini-2.5-pro", model_version="2025-05", status="draft", responsible_slug="ozan-yilmaz",
                skills=[
                    ("Data Analysis",  "1.0", "GA4, Mixpanel ve SQL tabanlı çok boyutlu raporlama"),
                    ("Visualization",  "0.9", "Looker Studio ve custom dashboard oluşturma"),
                    ("A/B Testing",    "0.8", "Deney tasarımı, istatistiksel anlamlılık ve sonuç yorumlama"),
                ]
            ),
            # Finans
            dict(
                name="LedgerAI", slug="ledgerai", title="Finance & Reporting Agent",
                department_id=dept_map["finans"], manager_id=hm["mert-arslan"],
                model="gpt-4o", model_version="2024-11", status="active", responsible_slug="mert-arslan",
                skills=[
                    ("Forecasting",  "1.2", "Nakit akışı tahmini, senaryo analizi ve bütçe sapma tespiti"),
                    ("Reporting",    "2.0", "Aylık/çeyreklik finansal rapor otomasyonu ve yönetici özetleri"),
                    ("Compliance",   "1.0", "KDV, stopaj ve diğer vergi yükümlülükleri kontrol ve uyarı"),
                    ("Reconciliation","1.0","Banka ekstresi mutabakatı ve fatura eşleştirme otomasyonu"),
                ]
            ),
            # İnsan Kaynakları
            dict(
                name="TalentScout", slug="talentscout", title="Recruitment Assistant Agent",
                department_id=dept_map["insan-kaynaklari"], manager_id=hm["ayse-kara"],
                model="claude-sonnet-4", model_version="4.6", status="active", responsible_slug="ayse-kara",
                skills=[
                    ("CV Screening",     "1.0", "CV analizi, kriterlere göre skorlama ve shortlist oluşturma"),
                    ("JD Writing",       "1.1", "İş ilanı yazımı, gereksinim belirleme ve kanal önerisi"),
                    ("Interview Prep",   "0.9", "Pozisyona özel teknik ve yetkinlik bazlı soru seti hazırlama"),
                ]
            ),
            # Müşteri Başarısı
            dict(
                name="SupportBot", slug="supportbot", title="Customer Support Agent",
                department_id=dept_map["musteri-basarisi"], manager_id=hm["deniz-ozturk"],
                model="claude-sonnet-4", model_version="4.6", status="active", responsible_slug="deniz-ozturk",
                skills=[
                    ("Ticket Triage",    "1.2", "Destek talebi önceliklendirme ve doğru ekibe yönlendirme"),
                    ("FAQ Generation",   "1.0", "Geçmiş biletlerden otomatik SSS ve knowledge base oluşturma"),
                    ("Churn Detection",  "0.9", "Risk sinyali analizi ve müşteri kaybı erken uyarı sistemi"),
                ]
            ),
            dict(
                name="OnboardAI", slug="onboardai", title="Customer Onboarding Agent",
                department_id=dept_map["musteri-basarisi"], manager_id=hm["deniz-ozturk"],
                model="gemini-2.5-pro", model_version="2025-05", status="draft", responsible_slug="deniz-ozturk",
                skills=[
                    ("Onboarding Flow", "0.8", "Müşteri segmentine özel adım adım onboarding planı oluşturma"),
                    ("Progress Track",  "0.7", "Milestone takibi ve gecikme durumunda proaktif müdahale önerisi"),
                ]
            ),
        ]

        for ad in agent_defs:
            p = Personnel(
                name=ad["name"], slug=ad["slug"], title=ad["title"],
                type="agent", department_id=ad["department_id"], manager_id=ad["manager_id"]
            )
            session.add(p)
            session.flush()

            cfg = AgentConfig(
                personnel_id=p.id,
                model=ad["model"],
                model_version=ad["model_version"],
                status=ad["status"],
                responsible_id=hm[ad["responsible_slug"]],
            )
            session.add(cfg)
            session.flush()

            for (sname, sver, sdesc) in ad["skills"]:
                session.add(Skill(agent_id=cfg.id, name=sname, version=sver, description=sdesc))

        session.commit()
        print("✅ Seed data inserted — 6 departments, 10 humans, 9 agents")


# ── Schemas ────────────────────────────────────────────────────────────────────

class DepartmentCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    goals: Optional[str] = None
    policies: list[str] = []
    status: str = "Active"

class DepartmentUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    goals: Optional[str] = None
    policies: Optional[list[str]] = None
    status: Optional[str] = None

class PersonnelCreate(BaseModel):
    name: str
    slug: str
    title: Optional[str] = None
    role: Optional[str] = None
    type: str = "human"
    department_id: Optional[str] = None
    manager_id: Optional[str] = None

class PersonnelUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    title: Optional[str] = None
    role: Optional[str] = None
    type: Optional[str] = None
    department_id: Optional[str] = None
    manager_id: Optional[str] = None

class AgentConfigCreate(BaseModel):
    model: str
    model_version: Optional[str] = None
    status: str = "draft"
    responsible_id: Optional[str] = None

class AgentConfigUpdate(BaseModel):
    model: Optional[str] = None
    model_version: Optional[str] = None
    status: Optional[str] = None
    responsible_id: Optional[str] = None

class SkillCreate(BaseModel):
    name: str
    version: str
    description: Optional[str] = None


# ── Root ────────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "3rdParty Agent Organization API", "version": "0.2.0", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "healthy"}


# ── Departments ─────────────────────────────────────────────────────────────────

@app.get("/departments")
def list_departments():
    with Session(engine) as session:
        depts = session.exec(select(Department)).all()
        return [dept_to_dict(d) for d in depts]

@app.post("/departments", status_code=201)
def create_department(body: DepartmentCreate):
    with Session(engine) as session:
        dept = Department(
            name=body.name,
            slug=body.slug,
            description=body.description,
            goals=body.goals,
            policies_json=json.dumps(body.policies),
            status=body.status,
        )
        session.add(dept)
        session.commit()
        session.refresh(dept)
        return dept_to_dict(dept)

@app.get("/departments/{dept_id}")
def get_department(dept_id: str):
    with Session(engine) as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        return dept_to_dict(dept)

@app.patch("/departments/{dept_id}")
def update_department(dept_id: str, body: DepartmentUpdate):
    with Session(engine) as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        if body.name is not None:       dept.name = body.name
        if body.slug is not None:       dept.slug = body.slug
        if body.description is not None: dept.description = body.description
        if body.goals is not None:      dept.goals = body.goals
        if body.policies is not None:   dept.policies_json = json.dumps(body.policies)
        if body.status is not None:     dept.status = body.status
        session.add(dept)
        session.commit()
        session.refresh(dept)
        return dept_to_dict(dept)

@app.delete("/departments/{dept_id}", status_code=204)
def delete_department(dept_id: str):
    with Session(engine) as session:
        dept = session.get(Department, dept_id)
        if not dept:
            raise HTTPException(status_code=404, detail="Department not found")
        session.delete(dept)
        session.commit()


# ── Personnel ──────────────────────────────────────────────────────────────────

def personnel_to_dict(p: Personnel, session: Session) -> dict:
    dept = session.get(Department, p.department_id) if p.department_id else None
    manager = session.get(Personnel, p.manager_id) if p.manager_id else None
    cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == p.id)).first()

    result = {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "title": p.title,
        "role": p.role,
        "type": p.type,
        "department_id": p.department_id,
        "department_name": dept.name if dept else None,
        "manager_id": p.manager_id,
        "manager_name": manager.name if manager else None,
        "created_at": p.created_at.isoformat(),
    }

    if cfg:
        responsible = session.get(Personnel, cfg.responsible_id) if cfg.responsible_id else None
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        result["agent_config"] = {
            "id": cfg.id,
            "model": cfg.model,
            "model_version": cfg.model_version,
            "status": cfg.status,
            "responsible_id": cfg.responsible_id,
            "responsible_name": responsible.name if responsible else None,
            "skills": [{"id": s.id, "name": s.name, "version": s.version, "description": s.description} for s in skills],
        }

    return result

@app.get("/personnel")
def list_personnel(department_id: Optional[str] = None, type: Optional[str] = None):
    with Session(engine) as session:
        q = select(Personnel)
        if department_id:
            q = q.where(Personnel.department_id == department_id)
        if type:
            q = q.where(Personnel.type == type)
        people = session.exec(q).all()
        return [personnel_to_dict(p, session) for p in people]

@app.post("/personnel", status_code=201)
def create_personnel(body: PersonnelCreate):
    with Session(engine) as session:
        person = Personnel(
            name=body.name,
            slug=body.slug,
            title=body.title,
            role=body.role,
            type=body.type,
            department_id=body.department_id,
            manager_id=body.manager_id,
        )
        session.add(person)
        session.commit()
        session.refresh(person)
        return personnel_to_dict(person, session)

@app.get("/personnel/{person_id}")
def get_personnel(person_id: str):
    with Session(engine) as session:
        person = session.get(Personnel, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Personnel not found")
        return personnel_to_dict(person, session)

@app.patch("/personnel/{person_id}")
def update_personnel(person_id: str, body: PersonnelUpdate):
    with Session(engine) as session:
        person = session.get(Personnel, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Personnel not found")
        if body.name is not None:          person.name = body.name
        if body.slug is not None:          person.slug = body.slug
        if body.title is not None:         person.title = body.title
        if body.role is not None:          person.role = body.role
        if body.type is not None:          person.type = body.type
        if body.department_id is not None: person.department_id = body.department_id
        if body.manager_id is not None:    person.manager_id = body.manager_id
        session.add(person)
        session.commit()
        session.refresh(person)
        return personnel_to_dict(person, session)

@app.delete("/personnel/{person_id}", status_code=204)
def delete_personnel(person_id: str):
    with Session(engine) as session:
        person = session.get(Personnel, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Personnel not found")
        session.delete(person)
        session.commit()


# ── Agent Config ───────────────────────────────────────────────────────────────

@app.get("/personnel/{person_id}/agent-config")
def get_agent_config(person_id: str):
    with Session(engine) as session:
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        return {
            "id": cfg.id,
            "personnel_id": cfg.personnel_id,
            "model": cfg.model,
            "model_version": cfg.model_version,
            "status": cfg.status,
            "responsible_id": cfg.responsible_id,
            "skills": [{"id": s.id, "name": s.name, "version": s.version, "description": s.description} for s in skills],
            "created_at": cfg.created_at.isoformat(),
            "updated_at": cfg.updated_at.isoformat(),
        }

@app.post("/personnel/{person_id}/agent-config", status_code=201)
def create_agent_config(person_id: str, body: AgentConfigCreate):
    with Session(engine) as session:
        person = session.get(Personnel, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Personnel not found")
        existing = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Agent config already exists")
        cfg = AgentConfig(
            personnel_id=person_id,
            model=body.model,
            model_version=body.model_version,
            status=body.status,
            responsible_id=body.responsible_id,
        )
        session.add(cfg)
        # mark personnel as agent type
        person.type = "agent"
        session.add(person)
        session.commit()
        session.refresh(cfg)
        return {"id": cfg.id, "personnel_id": cfg.personnel_id, "model": cfg.model,
                "model_version": cfg.model_version, "status": cfg.status,
                "responsible_id": cfg.responsible_id, "skills": []}

@app.patch("/personnel/{person_id}/agent-config")
def update_agent_config(person_id: str, body: AgentConfigUpdate):
    with Session(engine) as session:
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        if body.model is not None:          cfg.model = body.model
        if body.model_version is not None:  cfg.model_version = body.model_version
        if body.status is not None:         cfg.status = body.status
        if body.responsible_id is not None: cfg.responsible_id = body.responsible_id
        cfg.updated_at = datetime.utcnow()
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        return {"id": cfg.id, "model": cfg.model, "model_version": cfg.model_version,
                "status": cfg.status, "responsible_id": cfg.responsible_id,
                "skills": [{"id": s.id, "name": s.name, "version": s.version, "description": s.description} for s in skills]}


# ── Skills ────────────────────────────────────────────────────────────────────

@app.get("/personnel/{person_id}/skills")
def list_skills(person_id: str):
    with Session(engine) as session:
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        skills = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
        return [{"id": s.id, "name": s.name, "version": s.version, "description": s.description} for s in skills]

@app.post("/personnel/{person_id}/skills", status_code=201)
def add_skill(person_id: str, body: SkillCreate):
    with Session(engine) as session:
        cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == person_id)).first()
        if not cfg:
            raise HTTPException(status_code=404, detail="Agent config not found")
        skill = Skill(agent_id=cfg.id, name=body.name, version=body.version, description=body.description)
        session.add(skill)
        session.commit()
        session.refresh(skill)
        return {"id": skill.id, "name": skill.name, "version": skill.version, "description": skill.description}

@app.delete("/personnel/{person_id}/skills/{skill_id}", status_code=204)
def delete_skill(person_id: str, skill_id: str):
    with Session(engine) as session:
        skill = session.get(Skill, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        session.delete(skill)
        session.commit()


# ── Org Tree ──────────────────────────────────────────────────────────────────

@app.get("/org-tree")
def get_org_tree():
    with Session(engine) as session:
        all_personnel = session.exec(select(Personnel)).all()
        all_configs   = session.exec(select(AgentConfig)).all()
        all_skills    = session.exec(select(Skill)).all()
        all_depts     = session.exec(select(Department)).all()

        dept_map  = {d.id: d for d in all_depts}
        cfg_map   = {c.personnel_id: c for c in all_configs}
        skills_by_agent = {}
        for s in all_skills:
            skills_by_agent.setdefault(s.agent_id, []).append({"name": s.name, "version": s.version, "description": s.description})

        def build_node(p: Personnel) -> dict:
            cfg = cfg_map.get(p.id)
            responsible = None
            if cfg and cfg.responsible_id:
                r = next((x for x in all_personnel if x.id == cfg.responsible_id), None)
                responsible = r.name if r else None

            dept = dept_map.get(p.department_id) if p.department_id else None
            node: dict = {
                "id": p.id,
                "name": p.name,
                "title": p.title or p.role or "",
                "type": p.type,
                "department": dept.name if dept else None,
                "children": [],
            }
            if cfg:
                node["model"]           = cfg.model
                node["modelVersion"]    = cfg.model_version
                node["agentStatus"]     = cfg.status
                node["responsibleHuman"] = responsible
                node["skills"]          = skills_by_agent.get(cfg.id, [])
                dept_policies: list[str] = dept.policies() if dept else []
                node["policies"]        = dept_policies

            return node

        nodes = {p.id: build_node(p) for p in all_personnel}

        roots: list[dict] = []
        for p in all_personnel:
            node = nodes[p.id]
            if p.manager_id and p.manager_id in nodes:
                nodes[p.manager_id]["children"].append(node)
            else:
                roots.append(node)

        return roots


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
