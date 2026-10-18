"""Git sync keeps one working copy per connection (Codex review #3, finding 3)."""

import subprocess

import pytest

from core.security import encrypt
from models import AgentConfig, GitConfig
from services import git_service as gs
from tests.conftest import make_agent_config, make_company, make_personnel


def _bare(path):
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(path)],
        check=True,
        capture_output=True,
    )
    # seed an initial commit so clone/pull have a branch
    work = path.parent / (path.name + "-seed")
    subprocess.run(
        ["git", "clone", str(path), str(work)], check=True, capture_output=True
    )
    (work / "README.md").write_text("seed")
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": "/usr/bin:/bin",
    }
    subprocess.run(
        ["git", "-C", str(work), "add", "."], check=True, capture_output=True, env=env
    )
    subprocess.run(
        ["git", "-C", str(work), "commit", "-m", "seed"],
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "origin", "HEAD:main"],
        check=True,
        capture_output=True,
        env=env,
    )
    return str(path)


@pytest.fixture()
def two_tenants(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "REPO_ROOT", tmp_path / "copies")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    out = []
    for i, name in enumerate(("a", "b")):
        co = make_company(db_session, name=f"Co {name}", slug=f"co-{name}")
        agent = make_personnel(
            db_session, co.id, name=f"Bot {name}", slug="shared-slug", type="agent"
        )
        cfg = make_agent_config(db_session, agent.id, model=f"model-{name}")
        remote = _bare(tmp_path / f"remote-{name}.git")
        gc = GitConfig(
            company_id=co.id,
            provider="github",
            repo_url=remote,
            branch="main",
            encrypted_token=encrypt("x"),
        )
        db_session.add(gc)
        db_session.commit()
        out.append((co, agent, cfg, gc, remote))
    return out


def test_each_connection_has_its_own_working_copy_and_remote(db_session, two_tenants):
    (co_a, _, _, gc_a, remote_a), (co_b, _, _, gc_b, remote_b) = two_tenants
    assert gs.repo_dir(gc_a) != gs.repo_dir(gc_b)
    log_a = gs.git_service.push(db_session, gc_a, "a")
    log_b = gs.git_service.push(db_session, gc_b, "b")
    assert log_a.status == "success" and log_b.status == "success", (
        log_a.message,
        log_b.message,
    )
    # sentinel content stays in its own tenant's remote even with the same slug
    for remote, model, other in (
        (remote_a, "model-a", "model-b"),
        (remote_b, "model-b", "model-a"),
    ):
        show = subprocess.run(
            ["git", "--git-dir", remote, "show", "main:agents/shared-slug/agent.yaml"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert model in show and other not in show


def test_a_pull_only_touches_the_connections_own_company(db_session, two_tenants):
    (co_a, agent_a, cfg_a, gc_a, _), (co_b, agent_b, cfg_b, gc_b, _) = two_tenants
    gs.git_service.push(db_session, gc_a, "a")
    # edit tenant A's file in A's working copy and push it to A's remote
    path = gs.repo_dir(gc_a) / "agents" / "shared-slug" / "agent.yaml"
    path.write_text(path.read_text().replace("model-a", "model-changed"))
    repo = gs.git_service._get_repo(gc_a)
    repo.index.add(["agents/shared-slug/agent.yaml"])
    repo.index.commit("edit")
    repo.remotes.origin.push("main")
    gs.git_service.pull(db_session, gc_a)
    db_session.expire_all()
    assert db_session.get(AgentConfig, cfg_a.id).model == "model-changed"
    assert (
        db_session.get(AgentConfig, cfg_b.id).model == "model-b"
    )  # same slug, other tenant


def test_unsafe_slugs_cannot_leave_the_working_copy(db_session, two_tenants):
    (co_a, agent_a, _, gc_a, _), _ = two_tenants
    agent_a.slug = "../../outside"
    db_session.add(agent_a)
    db_session.commit()
    log = gs.git_service.push(db_session, gc_a, "x")
    assert log.status == "error" and "unsafe" in (log.message or "")
    assert not (gs.REPO_ROOT.parent / "outside").exists()
