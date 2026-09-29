"""
Commits a single file to a GitHub repo via the GitHub Contents API (PyGithub).
No local git clone needed — purely API-based.
"""

import json

from github import Github, GithubException
from sqlmodel import Session

from core.security import decrypt
from models import ChangeRequest, GitConfig, Personnel


def _build_agent_yaml_content(
    session: Session,
    personnel_id: str,
    proposed: dict,
    change_type: str,
) -> tuple[str, str]:
    """Returns (file_path, yaml_content) for the changed agent."""
    agent = session.get(Personnel, personnel_id)
    if not agent:
        raise ValueError(f"Personnel {personnel_id} not found")

    slug = agent.slug

    if change_type == "agent_config":
        content_lines = [
            f"id: {slug}",
            f"name: {agent.name}",
            f"title: {agent.title or ''}",
            f"model: {proposed.get('model', '')}",
            f"model_version: {proposed.get('model_version') or ''}",
            f"provider: {proposed.get('provider') or ''}",
            f"status: {proposed.get('status', 'draft')}",
            f"updated_at: {proposed.get('updated_at', '')}",
        ]
        return f"agents/{slug}/agent.yaml", "\n".join(content_lines) + "\n"

    elif change_type == "skill":
        skill_lines = [
            f"id: {slug}",
            f"name: {agent.name}",
            "skills:",
        ]
        for s in proposed.get("skills", []):
            skill_lines.append(f"  - name: {s.get('name', '')}")
            skill_lines.append(f"    version: {s.get('version', '')}")
            skill_lines.append(f"    description: {s.get('description') or ''}")
            skill_lines.append(f"    type: {s.get('skill_type', 'builtin')}")
            skill_lines.append(f"    active: {str(s.get('is_active', True)).lower()}")
        return f"agents/{slug}/skills.yaml", "\n".join(skill_lines) + "\n"

    elif change_type == "policy":
        policy_lines = [
            f"id: {slug}",
            f"name: {agent.name}",
            "policies:",
        ]
        for p in proposed.get("policies", []):
            policy_lines.append(f"  - {p}")
        return f"agents/{slug}/policy.yaml", "\n".join(policy_lines) + "\n"

    raise ValueError(f"Unknown change_type: {change_type}")


def commit_change_request(
    session: Session,
    cr: ChangeRequest,
    git_config: GitConfig,
    committer_name: str = "fab.engineering Bot",
    committer_email: str = "bot@fab.engineering",
) -> tuple[str, str]:
    """
    Commits the change request file to GitHub.
    Returns (commit_sha, commit_url).
    """
    token = decrypt(git_config.encrypted_token)
    g = Github(token)

    # Parse repo from URL: https://github.com/owner/repo
    repo_url = git_config.repo_url.rstrip("/")
    if "github.com" not in repo_url:
        raise ValueError("Only GitHub repos are supported for Change Request commits")

    parts = repo_url.split("github.com/")[-1].split("/")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse repo from URL: {repo_url}")
    repo_full_name = f"{parts[0]}/{parts[1]}"

    repo = g.get_repo(repo_full_name)
    branch = git_config.branch or "main"

    proposed = json.loads(cr.proposed_json)
    file_path, content = _build_agent_yaml_content(
        session, cr.personnel_id, proposed, cr.change_type
    )

    commit_message = (
        f"[Change Request] {cr.title}\n\n"
        f"Type: {cr.change_type}\n"
        f"CR ID: {cr.id}\n"
        f"Approved by admin at: {cr.admin_approved_at}"
    )

    try:
        existing = repo.get_contents(file_path, ref=branch)
        result = repo.update_file(
            path=file_path,
            message=commit_message,
            content=content,
            sha=existing.sha,
            branch=branch,
            committer={"name": committer_name, "email": committer_email},
        )
    except GithubException as e:
        if e.status == 404:
            result = repo.create_file(
                path=file_path,
                message=commit_message,
                content=content,
                branch=branch,
                committer={"name": committer_name, "email": committer_email},
            )
        else:
            raise

    commit = result["commit"]
    commit_sha = commit.sha
    commit_url = commit.html_url
    return commit_sha, commit_url
