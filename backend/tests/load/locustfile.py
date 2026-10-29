import os
import secrets
import time
from locust import FastHttpUser, HttpUser, task, between
from app.core.security import create_signed_oauth_state


class ValidSessionUser(FastHttpUser):
    wait_time = between(0.01, 0.05)
    weight = 5

    def on_start(self):
        self.token = os.getenv("LOAD_TEST_VALID_TOKEN", "")

    @task
    def get_me(self):
        with self.client.get(
            "/api/me",
            headers={"Cookie": f"session_token={self.token}"},
            catch_response=True,
            name="GET /api/me [Valid Session]"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Expected 200 but got {resp.status_code}")


class InvalidSessionUser(FastHttpUser):
    wait_time = between(0.01, 0.05)
    weight = 3

    @task
    def get_me_invalid(self):
        with self.client.get(
            "/api/me",
            headers={"Cookie": "session_token=forged_invalid_cookie_token_abc123"},
            catch_response=True,
            name="GET /api/me [Invalid/Forged 401]"
        ) as resp:
            if resp.status_code == 401:
                resp.success()
            else:
                resp.failure(f"Expected 401 but got {resp.status_code}")


class LogoutUser(FastHttpUser):
    wait_time = between(0.05, 0.1)
    weight = 2

    def on_start(self):
        self.token = os.getenv("LOAD_TEST_LOGOUT_TOKEN", "")

    @task
    def logout(self):
        with self.client.post(
            "/api/auth/logout",
            headers={
                "Origin": "http://localhost:5173",
                "Cookie": f"session_token={self.token}",
            },
            catch_response=True,
            name="POST /api/auth/logout"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Expected 200 but got {resp.status_code}")


class CallbackReturningUser(FastHttpUser):
    wait_time = between(0.05, 0.1)
    weight = 2

    @task
    def callback_returning(self):
        state = secrets.token_hex(16)
        nonce = "loadtest_nonce"
        signed_state = create_signed_oauth_state({
            "provider": "google",
            "state": state,
            "next": "/dashboard",
            "nonce": nonce,
            "code_verifier": "verifier_returning",
        })
        with self.client.get(
            f"/api/auth/callback/google?code=code_returning_{secrets.token_hex(4)}&state={state}",
            headers={"Cookie": f"oauth_state={signed_state}"},
            allow_redirects=False,
            catch_response=True,
            name="GET /api/auth/callback/google [Returning User]",
        ) as resp:
            if resp.status_code == 302:
                resp.success()
            else:
                resp.failure(f"Expected 302 but got {resp.status_code}")


class CallbackNewUser(FastHttpUser):
    wait_time = between(0.05, 0.1)
    weight = 2

    @task
    def callback_new(self):
        state = secrets.token_hex(16)
        nonce = "loadtest_nonce"
        signed_state = create_signed_oauth_state({
            "provider": "google",
            "state": state,
            "next": "/dashboard",
            "nonce": nonce,
            "code_verifier": "verifier_new",
        })
        with self.client.get(
            f"/api/auth/callback/google?code=code_new_{secrets.token_hex(4)}&state={state}",
            headers={"Cookie": f"oauth_state={signed_state}"},
            allow_redirects=False,
            catch_response=True,
            name="GET /api/auth/callback/google [New User]",
        ) as resp:
            if resp.status_code == 302:
                resp.success()
            else:
                resp.failure(f"Expected 302 but got {resp.status_code}")


class DiagnosticPingAsyncUser(FastHttpUser):
    wait_time = between(0.01, 0.05)

    @task
    def ping_async(self):
        with self.client.get(
            "/api/diagnostic/ping-async",
            catch_response=True,
            name="GET /api/diagnostic/ping-async [No-DB Async]"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Expected 200 but got {resp.status_code}")


class DiagnosticPingSyncUser(FastHttpUser):
    wait_time = between(0.01, 0.05)

    @task
    def ping_sync(self):
        with self.client.get(
            "/api/diagnostic/ping-sync",
            catch_response=True,
            name="GET /api/diagnostic/ping-sync [No-DB Sync]"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Expected 200 but got {resp.status_code}")


class DiagnosticDbPingUser(FastHttpUser):
    wait_time = between(0.01, 0.05)

    @task
    def db_ping(self):
        with self.client.get(
            "/api/diagnostic/db-ping",
            catch_response=True,
            name="GET /api/diagnostic/db-ping [SELECT 1]"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Expected 200 but got {resp.status_code}")


class RedirectLinkUser(FastHttpUser):
    wait_time = between(0.001, 0.005)

    @task
    def redirect_link(self):
        with self.client.get(
            "/redir50",
            headers={
                "Referer": "https://google.com/search?q=linksphere",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
            },
            allow_redirects=False,
            catch_response=True,
            name="GET /{short_code} [Redirect 302]"
        ) as resp:
            if resp.status_code == 302:
                resp.success()
            else:
                resp.failure(f"Expected 302 but got {resp.status_code}")


class PostLinkUser(FastHttpUser):
    wait_time = between(0.01, 0.05)

    def on_start(self):
        self.token = os.getenv("LOAD_TEST_HEAVY_TOKEN", os.getenv("LOAD_TEST_VALID_TOKEN", ""))

    @task
    def post_link(self):
        rand_slug = f"l_{secrets.token_hex(4)}"
        with self.client.post(
            "/api/links",
            json={"original_url": f"https://example.com/p/{rand_slug}"},
            headers={
                "Cookie": f"session_token={self.token}",
                "Origin": "http://localhost:5173",
            },
            catch_response=True,
            name="POST /api/links [Create Link]"
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            else:
                resp.failure(f"Expected 201 but got {resp.status_code}")


class GetLinksHeavyUser(FastHttpUser):
    wait_time = between(0.01, 0.05)

    def on_start(self):
        self.token = os.getenv("LOAD_TEST_HEAVY_TOKEN", "")

    @task
    def get_links(self):
        with self.client.get(
            "/api/links?limit=20&offset=0",
            headers={
                "Cookie": f"session_token={self.token}",
            },
            catch_response=True,
            name="GET /api/links [1000 Links + 100k Clicks]"
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Expected 200 but got {resp.status_code}")
