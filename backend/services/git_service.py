"""
Git sync service — handles clone/pull/push and YAML file I/O.

Repo layout (inside the connected git repo):
  agents/{slug}/agent.yaml      ← AgentConfig + Skills
  departments/{slug}/department.yaml  ← Department + policies list
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import yaml
from git import Repo, InvalidGitRepositoryError, NoSuchPathError
from sqlmodel import Session, select

from core.security import decrypt
from models import (
    AgentConfig, Department, GitConfig, Personnel, Skill, SyncLog,
)

REPO_DIR = Path("data/git-repo")


# ── YAML serialisers ──────────────────────────────────────────────────────────

def _agent_to_dict(
    agent: Personnel,
    cfg: AgentConfig,
    skills: list[Skill],
    dept: Optional[Department],
    responsible: Optional[Personnel],
) -> dict:
    return {
        "id":            agent.slug,
        "name":          agent.name,
        "title":         agent.title,
        "model":         cfg.model,
        "model_version": cfg.model_version,
        "status":        cfg.status,
        "department":    dept.slug if dept else None,
        "responsible":   responsible.slug if responsible else None,
        "skills": [
            {"name": s.name, "version": s.version, "description": s.description}
            for s in skills
        ],
        "updated_at": datetime.utcnow().date().isoformat(),
    }


def _dept_to_dict(dept: Department) -> dict:
    return {
        "id":          dept.slug,
        "name":        dept.name,
        "description": dept.description,
        "status":      dept.status,
        "goals":       dept.goals,
        "policies":    dept.policies(),
        "updated_at":  datetime.utcnow().date().isoformat(),
    }


# ── Service ───────────────────────────────────────────────────────────────────

class GitSyncService:

    # ── Auth URL ──────────────────────────────────────────────────────────────

    def _auth_url(self, config: GitConfig) -> str:
        url = config.repo_url.rstrip("/")
        # Local paths (file://, /path, relative) — no auth needed
        if url.startswith("file://") or url.startswith("/") or not url.startswith("http"):
            return url
        token = decrypt(config.encrypted_token).strip()
        if not url.endswith(".git"):
            url += ".git"
        if config.provider in ("github", "gitea"):
            return url.replace("https://", f"https://{token}@")
        if config.provider == "gitlab":
            return url.replace("https://", f"https://oauth2:{token}@")
        return url

    # ── Repo access ───────────────────────────────────────────────────────────

    def _get_repo(self, config: GitConfig) -> Repo:
        """Clone once, then reuse. Re-injects auth on every call."""
        try:
            repo = Repo(REPO_DIR)
            with repo.remotes.origin.config_writer as cw:
                cw.set("url", self._auth_url(config))
        except (InvalidGitRepositoryError, NoSuchPathError):
            REPO_DIR.mkdir(parents=True, exist_ok=True)
            repo = Repo.clone_from(self._auth_url(config), REPO_DIR, branch=config.branch, depth=50)
        return repo

    def _parse_repo_url(self, config: GitConfig) -> tuple[str, str]:
        m = re.search(r"[:/]([^/]+)/([^/]+?)(?:\.git)?$", config.repo_url)
        if not m:
            raise ValueError(f"Repo URL ayrıştırılamadı: {config.repo_url}")
        return m.group(1), m.group(2)

    # ── Export (DB → YAML files) ──────────────────────────────────────────────

    def export_to_files(self, session: Session, company_id: Optional[str] = None) -> list[Path]:
        written: list[Path] = []

        dept_q = select(Department)
        if company_id:
            dept_q = dept_q.where(Department.company_id == company_id)
        for dept in session.exec(dept_q).all():
            path = REPO_DIR / "departments" / f"{dept.slug}.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.dump(_dept_to_dict(dept), allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            written.append(path)

        agent_q = select(Personnel).where(Personnel.type == "agent")
        if company_id:
            agent_q = agent_q.where(Personnel.company_id == company_id)
        for agent in session.exec(agent_q).all():
            cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == agent.id)).first()
            if not cfg:
                continue
            skills    = session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all()
            dept      = session.get(Department, agent.department_id) if agent.department_id else None
            responsible = session.get(Personnel, cfg.responsible_id) if cfg.responsible_id else None

            path = REPO_DIR / "agents" / agent.slug / "agent.yaml"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.dump(
                    _agent_to_dict(agent, cfg, list(skills), dept, responsible),
                    allow_unicode=True, default_flow_style=False, sort_keys=False,
                ),
                encoding="utf-8",
            )
            written.append(path)

        return written

    # ── Import (YAML files → DB) ──────────────────────────────────────────────

    def import_from_files(self, session: Session, company_id: Optional[str] = None) -> int:
        changed = 0

        dept_dir = REPO_DIR / "departments"
        if dept_dir.exists():
            for f in dept_dir.glob("*.yaml"):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    slug = data.get("id") or f.stem
                    q = select(Department).where(Department.slug == slug)
                    if company_id:
                        q = q.where(Department.company_id == company_id)
                    dept = session.exec(q).first()
                    if not dept:
                        continue
                    if data.get("name"):        dept.name        = data["name"]
                    if data.get("description"): dept.description = data["description"]
                    if data.get("status"):      dept.status      = data["status"]
                    if data.get("goals"):       dept.goals       = data["goals"]
                    if "policies" in data:
                        dept.policies_json = json.dumps(data["policies"])
                    session.add(dept)
                    changed += 1
                except Exception as exc:
                    print(f"  ! import dept {f.name}: {exc}")

        agents_dir = REPO_DIR / "agents"
        if agents_dir.exists():
            for f in agents_dir.glob("*/agent.yaml"):
                try:
                    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                    slug  = data.get("id") or f.parent.name
                    q = select(Personnel).where(Personnel.slug == slug)
                    if company_id:
                        q = q.where(Personnel.company_id == company_id)
                    agent = session.exec(q).first()
                    if not agent:
                        continue
                    cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == agent.id)).first()
                    if not cfg:
                        continue
                    if data.get("model"):         cfg.model         = data["model"]
                    if data.get("model_version"): cfg.model_version = data["model_version"]
                    if data.get("status"):        cfg.status        = data["status"]
                    cfg.updated_at = datetime.utcnow()
                    session.add(cfg)

                    if "skills" in data and isinstance(data["skills"], list):
                        for old in session.exec(select(Skill).where(Skill.agent_id == cfg.id)).all():
                            session.delete(old)
                        for sd in data["skills"]:
                            session.add(Skill(
                                agent_id=cfg.id,
                                name=sd.get("name", ""),
                                version=sd.get("version", ""),
                                description=sd.get("description"),
                            ))
                    changed += 1
                except Exception as exc:
                    print(f"  ! import agent {f}: {exc}")

        session.commit()
        return changed

    # ── Pull (repo → DB) ──────────────────────────────────────────────────────

    def pull(self, session: Session, config: GitConfig) -> SyncLog:
        log = SyncLog(direction="pull", status="error")
        try:
            repo = self._get_repo(config)
            repo.remotes.origin.pull(config.branch)

            sha     = repo.head.commit.hexsha
            count   = self.import_from_files(session, company_id=config.company_id)

            config.last_synced     = datetime.utcnow()
            config.last_commit_sha = sha
            config.status          = "connected"
            session.add(config)

            log.status        = "success"
            log.files_changed = count
            log.commit_sha    = sha
            log.message       = f"{count} kayıt güncellendi"

        except Exception as exc:
            config.status = "error"
            session.add(config)
            log.message = str(exc)

        session.add(log)
        session.commit()
        session.refresh(log)
        return log

    # ── Push (DB → repo) ──────────────────────────────────────────────────────

    def push(self, session: Session, config: GitConfig, commit_message: str = "") -> SyncLog:
        log = SyncLog(direction="push", status="error")
        try:
            repo = self._get_repo(config)
            repo.remotes.origin.pull(config.branch)

            written = self.export_to_files(session, company_id=config.company_id)
            if not written:
                log.status  = "no_changes"
                log.message = "Dışa aktarılacak kayıt yok"
                session.add(log)
                session.commit()
                session.refresh(log)
                return log

            rel_paths = [str(p.relative_to(REPO_DIR)) for p in written]
            repo.index.add(rel_paths)

            diff_staged   = repo.index.diff("HEAD")
            diff_untracked = repo.untracked_files
            if not diff_staged and not diff_untracked:
                log.status  = "no_changes"
                log.message = "Dosyalar değişmedi, commit atlanıyor"
                session.add(log)
                session.commit()
                session.refresh(log)
                return log

            msg    = commit_message or f"chore: sync from platform [{datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"
            commit = repo.index.commit(msg)
            repo.remotes.origin.push(config.branch)

            sha    = commit.hexsha
            pr_url: Optional[str] = None
            if config.auto_pr:
                try:
                    pr_url = self._create_pr(config, msg)
                except Exception:
                    pass

            config.last_synced     = datetime.utcnow()
            config.last_commit_sha = sha
            config.status          = "connected"
            session.add(config)

            log.status        = "success"
            log.files_changed = len(written)
            log.commit_sha    = sha
            log.pr_url        = pr_url
            log.message       = f"{len(written)} dosya commit edildi"

        except Exception as exc:
            config.status = "error"
            session.add(config)
            log.message = str(exc)

        session.add(log)
        session.commit()
        session.refresh(log)
        return log

    # ── Diff (DB vs repo) ─────────────────────────────────────────────────────

    def diff(self, session: Session, config: GitConfig) -> list[dict]:
        try:
            repo = self._get_repo(config)
            repo.remotes.origin.pull(config.branch)
        except Exception as exc:
            return [{"error": str(exc)}]

        diffs: list[dict] = []

        agent_q = select(Personnel).where(Personnel.type == "agent")
        if config.company_id:
            agent_q = agent_q.where(Personnel.company_id == config.company_id)
        for agent in session.exec(agent_q).all():
            yaml_path = REPO_DIR / "agents" / agent.slug / "agent.yaml"
            cfg = session.exec(select(AgentConfig).where(AgentConfig.personnel_id == agent.id)).first()
            if not cfg:
                continue
            if not yaml_path.exists():
                diffs.append({"type": "agent", "slug": agent.slug, "change": "missing_in_repo"})
                continue
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
                if data.get("model") != cfg.model or data.get("status") != cfg.status:
                    diffs.append({
                        "type":   "agent",
                        "slug":   agent.slug,
                        "change": "modified",
                        "db":     {"model": cfg.model,         "status": cfg.status},
                        "repo":   {"model": data.get("model"), "status": data.get("status")},
                    })
            except Exception:
                diffs.append({"type": "agent", "slug": agent.slug, "change": "parse_error"})

        dept_q = select(Department)
        if config.company_id:
            dept_q = dept_q.where(Department.company_id == config.company_id)
        for dept in session.exec(dept_q).all():
            yaml_path = REPO_DIR / "departments" / f"{dept.slug}.yaml"
            if not yaml_path.exists():
                diffs.append({"type": "department", "slug": dept.slug, "change": "missing_in_repo"})

        return diffs

    # ── PR creation (GitHub / GitLab) ─────────────────────────────────────────

    def _create_pr(self, config: GitConfig, title: str) -> Optional[str]:
        token = decrypt(config.encrypted_token)
        owner, repo = self._parse_repo_url(config)

        if config.provider == "github":
            resp = httpx.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={
                    "title": title,
                    "head":  config.branch,
                    "base":  config.branch,
                    "body":  "Otomatik sync — 3rdParty Agent Platform",
                },
                timeout=10,
            )
            if resp.status_code == 201:
                return resp.json().get("html_url")

        elif config.provider == "gitlab":
            encoded = f"{owner}%2F{repo}"
            resp = httpx.post(
                f"https://gitlab.com/api/v4/projects/{encoded}/merge_requests",
                headers={"Authorization": f"Bearer {token}"},
                json={"title": title, "source_branch": config.branch, "target_branch": config.branch},
                timeout=10,
            )
            if resp.status_code == 201:
                return resp.json().get("web_url")

        return None


git_service = GitSyncService()
