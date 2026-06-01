export type AgentSkill = {
	name: string;
	version: string;
	description: string;
};

export type OrgNode = {
	id: string;
	name: string;
	title: string;
	type: 'human' | 'agent';
	department: string | null;
	// Agent-only
	model?: string;
	modelVersion?: string;
	agentStatus?: 'active' | 'draft' | 'inactive';
	skills?: AgentSkill[];
	policies?: string[];
	responsibleHuman?: string;
	// Tree
	children?: OrgNode[];
};
