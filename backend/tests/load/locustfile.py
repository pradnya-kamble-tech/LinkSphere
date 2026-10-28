from gevent import monkey
monkey.patch_all()

import os
from locust import FastHttpUser, task, between


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
