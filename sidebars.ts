import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  tutorialSidebar: [
    'intro',
    {
      type: 'category',
      label: 'Başlarken',
      items: ['getting-started/installation', 'getting-started/quickstart'],
    },
    {
      type: 'category',
      label: 'Agent Kullanımı',
      items: ['getting-started/agent-usage'],
    },
    {
      type: 'category',
      label: 'Pitch Deck',
      items: ['pitch-deck/overview', 'pitch-deck/problem', 'pitch-deck/solution'],
    },
    {
      type: 'category',
      label: 'API Dokümantasyonu',
      items: ['api/overview', 'api/authentication'],
    },
    {
      type: 'category',
      label: 'Mimari',
      items: ['architecture/overview'],
    },
  ],
};

export default sidebars;