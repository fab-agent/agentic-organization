import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  tutorialSidebar: [
    'intro',
    'changelog',
    {
      type: 'category',
      label: 'Başlarken',
      items: ['getting-started/installation', 'getting-started/user-roles', 'getting-started/agent-usage'],
    },
    {
      type: 'category',
      label: 'Ürün',
      items: [
        'product/admin-panel',
        'product/personnel-portal',
        'product/agent-management',
        'product/policy-and-skills',
        'product/department-hierarchy',
        'product/change-requests',
        'product/github-integration',
        'product/autonomous-flows',
        'product/task-requests',
        'product/inbox',
        'product/a2a-architecture',
        'product/a2a-delegation',
        'product/audit-log',
        'product/agent-memory',
        'product/flow-tool-use',
      ],
    },
    {
      type: 'category',
      label: 'Platform',
      items: [
        'platform/auth-and-roles',
        'platform/agent-runtime',
        'platform/chat-ui',
        'platform/a2a-delegation',
        'platform/message-rendering',
        'platform/backup',
        'platform/social-media-agent',
      ],
    },
    {
      type: 'category',
      label: 'Mimari',
      items: [
        'architecture/3rdparty-agent-org',
        'architecture/provider-key-management',
        'architecture/runtime',
        'architecture/skill-types',
        'architecture/company-reactive',
      ],
    },
    {
      type: 'category',
      label: 'İçgörüler',
      items: [
        'pitch-deck/overview',
        'pitch-deck/agentik-organizasyon-yapisi',
        'pitch-deck/policy-ve-guardrail',
        'pitch-deck/mcp-ve-skill-gelistirme',
      ],
    },
  ],
};

export default sidebars;