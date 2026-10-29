from gevent import monkey
monkey.patch_all()

import os
import secrets
import time
from locust import FastHttpUser, task, between
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
