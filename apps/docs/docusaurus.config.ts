import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'fab.engineering',
  tagline: 'Şirketinizin ajanlarını organize edin.',
  favicon: 'img/fab-logo.jpg',

  url: 'https://agent-docs.fab.engineering',
  baseUrl: '/',

  organizationName: 'fab-agent',
  projectName: 'docs',

  onBrokenLinks: 'throw',

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  i18n: {
    defaultLocale: 'tr',
    locales: ['tr', 'en'],
    localeConfigs: {
      tr: { label: 'Türkçe', direction: 'ltr' },
      en: { label: 'English', direction: 'ltr' },
    },
  },

  plugins: [
    [
      '@docusaurus/plugin-client-redirects',
      {
        // Eski /docs/* adresleri kök altına taşındı
        createRedirects(existingPath: string) {
          return existingPath === '/' ? undefined : [`/docs${existingPath}`];
        },
        // Yeniden yapılandırılan sayfaların eski adresleri
        redirects: Object.entries({
          '/intro': '/',
          '/getting-started/user-roles': '/guide/people-and-access',
          '/getting-started/agent-usage': '/getting-started/first-steps',
          '/product/admin-panel': '/guide/people-and-access',
          '/product/personnel-portal': '/guide/people-and-access',
          '/platform/auth-and-roles': '/guide/people-and-access',
          '/product/agent-management': '/guide/agents',
          '/product/policy-and-skills': '/guide/skills-and-policies',
          '/pitch-deck/policy-ve-guardrail': '/guide/skills-and-policies',
          '/pitch-deck/mcp-ve-skill-gelistirme': '/guide/skills-and-policies',
          '/product/department-hierarchy': '/guide/organization',
          '/pitch-deck/agentik-organizasyon-yapisi': '/guide/organization',
          '/product/change-requests': '/guide/change-requests',
          '/product/github-integration': '/guide/settings',
          '/platform/backup': '/guide/settings',
          '/platform/social-media-agent': '/guide/settings',
          '/architecture/provider-key-management': '/guide/settings',
          '/product/autonomous-flows': '/guide/flows',
          '/product/flow-tool-use': '/guide/flows',
          '/product/task-requests': '/guide/tasks-and-inbox',
          '/product/inbox': '/guide/tasks-and-inbox',
          '/product/a2a-architecture': '/guide/delegation',
          '/product/a2a-delegation': '/guide/delegation',
          '/platform/a2a-delegation': '/guide/delegation',
          '/product/audit-log': '/guide/dashboard',
          '/product/agent-memory': '/guide/chat',
          '/platform/chat-ui': '/guide/chat',
          '/platform/message-rendering': '/guide/chat',
          '/platform/agent-runtime': '/technical/runtime',
          '/architecture/runtime': '/technical/runtime',
          '/architecture/3rdparty-agent-org': '/technical/architecture',
          '/architecture/company-reactive': '/technical/architecture',
          '/architecture/skill-types': '/technical/skill-types',
          '/pitch-deck/overview': '/developer-notes/overview',
        }).map(([from, to]) => ({from: [from, `/docs${from}`], to})),
      },
    ],
  ],

  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
          routeBasePath: '/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],

  themeConfig: {
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'fab.engineering',
      logo: {
        alt: 'fab.engineering Logo',
        src: 'img/fab-logo.jpg',
        style: {height: '32px', width: 'auto', borderRadius: '6px'},
      },
      items: [
        {
          type: 'docSidebar',
          sidebarId: 'tutorialSidebar',
          position: 'left',
          label: 'Dokümantasyon',
        },
        {
          type: 'localeDropdown',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Ürün',
          items: [
            {label: 'agent.fab.engineering', href: 'https://agent.fab.engineering'},
            {label: 'GitHub', href: 'https://github.com/fab-agent/agentic-organization'},
          ],
        },
        {
          title: 'Şirket',
          items: [
            {label: 'fab.limited', href: 'https://fab.limited'},
            {label: 'fab.engineering', href: 'https://fab.engineering'},
            {label: 'LinkedIn', href: 'https://www.linkedin.com/in/kuntaykunt/'},
          ],
        },
      ],
      copyright: `© 2026 Fabrika Yazılım Ticaret Limited Şirketi · Kuntay Kunt`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
