import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Heading from '@theme/Heading';

const content = {
  tr: {
    badge: 'v1.1.2 · Üretime Hazır',
    tagline: 'Şirketlerin yapay zeka ajanlarını organize biçimde yönetmesini sağlayan self-hosted, açık kaynak platform.',
    ctaStart: 'Kuruluma Başla →',
    ctaDocs: 'Dokümantasyon',
    featuresTitle: 'Özellikler',
    featuresSubtitle: 'Agentik organizasyonu yönetmek için ihtiyaç duyduğunuz her şey',
    features: [
      {icon: '🧠', title: 'AI Onboarding', desc: 'Web araştırması yapıp sorular sorarak şirket yapısını otomatik oluşturur. Departmanlar, ajanlar ve yetkinlikler tek tıkla kurulur.'},
      {icon: '🤖', title: 'Ajan Yönetimi', desc: 'Her personele model, skill ve durum ataması yapın. Draft → Active → Inactive. Değişiklikler onay akışından geçer.'},
      {icon: '🔁', title: 'A2A Delegasyon', desc: 'Orkestratör ajan alt görevleri uzmanlara devreder; insan onayıyla çalışır, sonuçlar otomatik rapor olarak iletilir.'},
      {icon: '⏱️', title: 'Otonom Akışlar', desc: 'Cron zamanlamalı ajan görevleri. Sonuçlar inbox\'a düşer. Görsel üretimi dahil tüm sağlayıcılar desteklenir.'},
      {icon: '🔐', title: 'Güvenli Anahtar Yönetimi', desc: 'API anahtarları AES-256 ile şifrelenmiş saklanır. Anthropic, OpenAI, Google, Mistral, Qwen, Ollama, LM Studio.'},
      {icon: '🌿', title: 'Git Entegrasyonu', desc: "Ajan yapılandırmalarını YAML olarak Git'e yedekle. İki aşamalı onay akışı (dept_head → admin) sonrası otomatik commit."},
      {icon: '🗺️', title: 'Org Şeması', desc: 'Organizasyon hiyerarşisini görsel ağaçta inceleyin. Ajanlara tıklayarak model, skill ve politika detaylarını görün.'},
      {icon: '📊', title: 'Canlı Dashboard', desc: 'Şirket geneli token kullanımı, ajan SLA metrikleri ve kullanıcıya özel oturum istatistikleri.'},
      {icon: '🌍', title: 'Çok Dil & Çoklu Şirket', desc: 'Türkçe ve İngilizce arayüz. Tek platformdan birden fazla şirketi bağımsız yönetin.'},
    ],
    quickStartTitle: 'Hızlı Başlangıç',
    quickStartSubtitle: 'Tek komutla çalıştırın',
    quickStartUi: 'Arayüz',
    quickStartApi: 'API',
    ctaInstall: 'Kurulum Kılavuzu',
    ctaUsage: 'Kullanım Kılavuzu',
  },
  en: {
    badge: 'v1.1.2 · Production Ready',
    tagline: 'Self-hosted, open-source platform for companies to manage AI agents in a structured way.',
    ctaStart: 'Get Started →',
    ctaDocs: 'Documentation',
    featuresTitle: 'Features',
    featuresSubtitle: 'Everything you need to manage an agentic organization',
    features: [
      {icon: '🧠', title: 'AI Onboarding', desc: 'Researches your company online, asks a few questions, and generates your entire org structure — departments, agents, and skills — with one click.'},
      {icon: '🤖', title: 'Agent Management', desc: 'Assign model, skills, and status to each personnel member. Draft → Active → Inactive. Changes go through an approval workflow.'},
      {icon: '🔁', title: 'A2A Delegation', desc: 'Orchestrator agents delegate sub-tasks to specialists with human approval. Results are auto-compiled into an executive report.'},
      {icon: '⏱️', title: 'Autonomous Flows', desc: 'Cron-scheduled agent tasks that run independently and deliver results to the inbox. Supports all providers including image generation.'},
      {icon: '🔐', title: 'Secure Key Management', desc: 'API keys stored encrypted with AES-256. Anthropic, OpenAI, Google, Mistral, Qwen, Ollama, LM Studio.'},
      {icon: '🌿', title: 'Git Integration', desc: 'Back up agent configurations as YAML to Git. Two-stage approval (dept_head → admin) triggers an automated commit.'},
      {icon: '🗺️', title: 'Org Chart', desc: 'Explore the organization hierarchy in a visual tree. Click any agent node for model, status, skills, and policy details.'},
      {icon: '📊', title: 'Live Dashboard', desc: 'Company-wide token usage, per-agent SLA metrics, and personal session statistics.'},
      {icon: '🌍', title: 'Multi-Language & Multi-Company', desc: 'Turkish and English interface. Manage multiple companies independently from a single platform.'},
    ],
    quickStartTitle: 'Quick Start',
    quickStartSubtitle: 'Run with a single command',
    quickStartUi: 'UI',
    quickStartApi: 'API',
    ctaInstall: 'Installation Guide',
    ctaUsage: 'Usage Guide',
  },
};

type Locale = keyof typeof content;

function Hero({locale}: {locale: Locale}) {
  const c = content[locale];
  return (
    <div style={{
      background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #0f172a 100%)',
      padding: '5rem 1.5rem',
      textAlign: 'center',
      borderBottom: '1px solid #1e293b',
    }}>
      <div style={{maxWidth: 720, margin: '0 auto'}}>
        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 10,
          background: '#1e293b', border: '1px solid #334155',
          borderRadius: 999, padding: '6px 16px', marginBottom: '1.5rem',
          fontSize: 13, color: '#94a3b8',
        }}>
          <span style={{width: 8, height: 8, background: '#22c55e', borderRadius: '50%', display: 'inline-block'}}></span>
          {c.badge}
        </div>

        <Heading as="h1" style={{
          fontSize: 'clamp(2rem, 5vw, 3.25rem)', fontWeight: 700,
          color: '#f1f5f9', lineHeight: 1.15, marginBottom: '1rem', letterSpacing: '-0.02em',
        }}>
          Agentic<br />
          <span style={{color: '#6366f1'}}>Organization</span>
        </Heading>

        <p style={{
          fontSize: '1.125rem', color: '#94a3b8', maxWidth: 560,
          margin: '0 auto 2.5rem', lineHeight: 1.7,
        }}>
          {c.tagline}
        </p>

        <div style={{display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap'}}>
          <Link
            className="button button--primary button--lg"
            to="/docs/getting-started/installation"
            style={{borderRadius: 10, fontWeight: 600}}>
            {c.ctaStart}
          </Link>
          <Link
            className="button button--secondary button--lg"
            to="/docs/intro"
            style={{borderRadius: 10, fontWeight: 600, background: '#1e293b', border: '1px solid #334155', color: '#e2e8f0'}}>
            {c.ctaDocs}
          </Link>
        </div>
      </div>
    </div>
  );
}

function Features({locale}: {locale: Locale}) {
  const c = content[locale];
  return (
    <div style={{padding: '4rem 1.5rem', background: '#f8fafc'}}>
      <div style={{maxWidth: 1100, margin: '0 auto'}}>
        <Heading as="h2" style={{textAlign: 'center', marginBottom: '0.5rem', fontSize: '1.75rem', color: '#0f172a'}}>
          {c.featuresTitle}
        </Heading>
        <p style={{textAlign: 'center', color: '#64748b', marginBottom: '3rem'}}>
          {c.featuresSubtitle}
        </p>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '1.25rem',
        }}>
          {c.features.map(f => (
            <div key={f.title} style={{
              background: '#fff', borderRadius: 14,
              border: '1px solid #e2e8f0', padding: '1.5rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
            }}>
              <div style={{fontSize: '2rem', marginBottom: '0.75rem'}}>{f.icon}</div>
              <div style={{fontWeight: 600, fontSize: '0.975rem', marginBottom: '0.4rem', color: '#0f172a'}}>{f.title}</div>
              <div style={{fontSize: '0.875rem', color: '#64748b', lineHeight: 1.6}}>{f.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function QuickStart({locale}: {locale: Locale}) {
  const c = content[locale];
  return (
    <div style={{padding: '4rem 1.5rem', background: '#fff', borderTop: '1px solid #f1f5f9'}}>
      <div style={{maxWidth: 760, margin: '0 auto', textAlign: 'center'}}>
        <Heading as="h2" style={{fontSize: '1.75rem', marginBottom: '0.5rem', color: '#0f172a'}}>
          {c.quickStartTitle}
        </Heading>
        <p style={{color: '#64748b', marginBottom: '2rem'}}>
          {c.quickStartSubtitle}
        </p>
        <div style={{
          background: '#0f172a', borderRadius: 14, padding: '1.5rem 2rem',
          textAlign: 'left', fontFamily: 'monospace', fontSize: '0.925rem',
          color: '#e2e8f0', lineHeight: 2,
        }}>
          <span style={{color: '#94a3b8'}}>$ </span>
          <span style={{color: '#86efac'}}>git clone</span>
          <span> https://github.com/fab-agent/agentic-organization.git</span><br/>
          <span style={{color: '#94a3b8'}}>$ </span>
          <span style={{color: '#86efac'}}>cd</span>
          <span> agentic-organization</span><br/>
          <span style={{color: '#94a3b8'}}>$ </span>
          <span style={{color: '#86efac'}}>docker compose up</span>
          <span style={{color: '#fbbf24'}}> --build</span>
        </div>
        <p style={{color: '#64748b', marginTop: '1.5rem', fontSize: '0.9rem'}}>
          {c.quickStartUi} → <code>http://localhost:5173</code> &nbsp;·&nbsp; {c.quickStartApi} → <code>http://localhost:8000/docs</code>
        </p>
        <div style={{marginTop: '2rem', display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap'}}>
          <Link
            className="button button--primary"
            to="/docs/getting-started/installation"
            style={{borderRadius: 8, fontWeight: 600}}>
            {c.ctaInstall}
          </Link>
          <Link
            className="button button--secondary"
            to="/docs/getting-started/agent-usage"
            style={{borderRadius: 8, fontWeight: 600}}>
            {c.ctaUsage}
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function Home(): ReactNode {
  const {siteConfig, i18n: {currentLocale}} = useDocusaurusContext();
  const locale: Locale = currentLocale === 'en' ? 'en' : 'tr';
  return (
    <Layout title={siteConfig.title} description={content[locale].tagline}>
      <Hero locale={locale} />
      <Features locale={locale} />
      <QuickStart locale={locale} />
    </Layout>
  );
}
