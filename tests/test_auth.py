from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import PasswordMiddleware


def client(password: str) -> TestClient:
    app = FastAPI()
    app.add_middleware(PasswordMiddleware, password=password)

    @app.get("/")
    def home():
        return {"ok": True}

    return TestClient(app)


def test_password_required_and_checked():
    c = client("s3cret")
    r = c.get("/")
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Basic")
    assert c.get("/", auth=("anyone", "wrong")).status_code == 401
    assert c.get("/", headers={"Authorization": "Basic !!notbase64"}).status_code == 401
    assert c.get("/", auth=("anyone", "s3cret")).json() == {"ok": True}
