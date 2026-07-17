"""File upload endpoint tests — POST /sessions/{id}/files."""

import io

from tests.conftest import make_personnel


def _make_session(auth_client, db_session, slug: str) -> str:
    co = auth_client._test_company
    agent = make_personnel(
        db_session, co.id, name=f"Bot-{slug}", slug=slug, type="agent"
    )
    db_session.commit()
    sess = auth_client.post("/sessions", json={"personnel_id": agent.id})
    assert sess.status_code == 201
    return sess.json()["id"]


def test_upload_text_file(auth_client, db_session):
    session_id = _make_session(auth_client, db_session, "fu-text")
    r = auth_client.post(
        f"/sessions/{session_id}/files",
        files={
            "file": (
                "notes.txt",
                io.BytesIO(b"Hello world test document content."),
                "text/plain",
            )
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "text"
    assert data["filename"] == "notes.txt"
    assert "Hello world" in data["content"]
    assert data["mime_type"] == "text/plain"


def test_upload_pdf_file(auth_client, db_session):
    session_id = _make_session(auth_client, db_session, "fu-pdf")
    r = auth_client.post(
        f"/sessions/{session_id}/files",
        files={
            "file": ("report.pdf", io.BytesIO(b"%PDF-1.4 broken"), "application/pdf")
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "pdf"
    assert data["filename"] == "report.pdf"
    assert "[PDF" in data["content"]  # broken PDF → error message, not a crash


def test_upload_image_file(auth_client, db_session):
    session_id = _make_session(auth_client, db_session, "fu-img")
    # Minimal 1×1 white PNG
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    r = auth_client.post(
        f"/sessions/{session_id}/files",
        files={"file": ("photo.png", io.BytesIO(png_bytes), "image/png")},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "image"
    assert data["filename"] == "photo.png"
    assert data["content"].startswith("data:image/png;base64,")


def test_upload_to_closed_session_rejected(auth_client, db_session):
    session_id = _make_session(auth_client, db_session, "fu-closed")
    # Close the session
    auth_client.delete(f"/sessions/{session_id}")

    r = auth_client.post(
        f"/sessions/{session_id}/files",
        files={"file": ("doc.txt", io.BytesIO(b"content"), "text/plain")},
    )
    assert r.status_code == 409


def test_upload_requires_auth(client):
    # client fixture is unauthenticated — any session ID should yield 401
    r = client.post(
        "/sessions/any-id/files",
        files={"file": ("doc.txt", io.BytesIO(b"content"), "text/plain")},
    )
    assert r.status_code == 401


def test_upload_unknown_session_returns_404(auth_client):
    r = auth_client.post(
        "/sessions/nonexistent-id/files",
        files={"file": ("doc.txt", io.BytesIO(b"content"), "text/plain")},
    )
    assert r.status_code == 404


def test_upload_unsupported_binary_returns_400(auth_client, db_session):
    session_id = _make_session(auth_client, db_session, "fu-bin")
    r = auth_client.post(
        f"/sessions/{session_id}/files",
        files={
            "file": (
                "data.bin",
                io.BytesIO(b"\x00\x01\x02\x03\xff\xfe"),
                "application/octet-stream",
            )
        },
    )
    assert r.status_code == 400
