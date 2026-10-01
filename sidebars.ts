import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  tutorialSidebar: [
    {type: 'doc', id: 'intro', label: 'Giriş'},
    {
      type: 'category',
      label: 'Başlarken',
      items: ['getting-started/requirements', 'getting-started/installation', 'getting-started/first-steps'],
    },
    {
      type: 'category',
      label: 'Kullanım Kılavuzu',
      items: [
        'guide/onboarding',
        'guide/organization',
        'guide/people-and-access',
        'guide/agents',
        'guide/skills-and-policies',
        'guide/chat',
        'guide/flows',
        'guide/tasks-and-inbox',
        'guide/delegation',
        'guide/change-requests',
        'guide/dashboard',
        'guide/settings',
      ],
    },
    {
      type: 'category',
      label: 'Departman Çalışma Alanı (fab)',
      items: [
        'fab/overview',
        'fab/workspace',
        'fab/agent-and-context',
        'fab/work-review',
        'fab/fit-rubric',
        'fab/enablement',
      ],
    },
    {
      type: 'category',
      label: 'Geliştirici İş İstasyonu',
      items: [
        'workstation/overview',
        'workstation/llm-gateway',
        'workstation/policy-engine',
        'workstation/audit-chain',
        'workstation/identity',
        'workstation/cli',
        'workstation/sandbox',
        'workstation/injection-defense',
        'workstation/managed-config',
      ],
    },
    {
      type: 'category',
      label: 'Teknik',
      items: ['technical/architecture', 'technical/runtime', 'technical/skill-types', 'technical/security'],
    },
    {
      type: 'category',
      label: 'Geliştirici Notları',
      items: ['developer-notes/overview', 'developer-notes/known-limits'],
    },
    {type: 'doc', id: 'changelog', label: 'Sürüm Notları'},
  ],
};

export default sidebars;
