import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'fab.engineering',
  tagline: 'Şirketinizin ajanlarını organize edin.',
  favicon: 'img/favicon.svg',

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
        src: 'img/fab-logo.svg',
        srcDark: 'img/fab-logo-dark.svg',
        style: {height: '32px', width: 'auto'},
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
