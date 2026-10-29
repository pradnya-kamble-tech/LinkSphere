import json
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import threading
from authlib.jose import jwt, JsonWebKey

# Generate test RSA key
TEST_RSA_KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True)
TEST_PUB_KEY = TEST_RSA_KEY.as_dict(is_private=False)
TEST_PUB_KEY["kid"] = "loadtest-google-kid-1"
TEST_JWKS = {"keys": [TEST_PUB_KEY]}

# Pre-sign tokens to prevent burning CPU during high-concurrency benchmarks
PRE_SIGNED_RETURNING_TOKEN = None
PRE_SIGNED_NEW_TOKENS = []
PRE_SIGNED_INDEX = 0

def init_pre_signed_tokens():
    global PRE_SIGNED_RETURNING_TOKEN, PRE_SIGNED_NEW_TOKENS
    now = int(time.time())
    hdr = {"alg": "RS256", "kid": "loadtest-google-kid-1"}
    
    # 1. Returning user token
    ret_claims = {
        "iss": "https://accounts.google.com",
        "aud": "test_google",
        "sub": "google-returning-load-sub",
        "email": "loadtest_returning@example.com",
        "email_verified": True,
        "name": "Load Returning User",
        "picture": "https://example.com/avatar.png",
        "nonce": "loadtest_nonce",
        "exp": now + 7200,
        "iat": now,
    }
    PRE_SIGNED_RETURNING_TOKEN = jwt.encode(hdr, ret_claims, TEST_RSA_KEY).decode("utf-8")

    # 2. Pool of 2000 unique new user tokens
    for i in range(2000):
        new_claims = {
            "iss": "https://accounts.google.com",
            "aud": "test_google",
            "sub": f"google-new-{i}",
            "email": f"loadnew_{i}_{now}@example.com",
            "email_verified": True,
            "name": f"Load New User {i}",
            "picture": "https://example.com/avatar.png",
            "nonce": "loadtest_nonce",
            "exp": now + 7200,
            "iat": now,
        }
        PRE_SIGNED_NEW_TOKENS.append(jwt.encode(hdr, new_claims, TEST_RSA_KEY).decode("utf-8"))

init_pre_signed_tokens()
    def log_message(self, format, *args):
        # Silence logging for performance
        pass

    def do_GET(self):
        if self.path == "/certs":
            body = json.dumps(TEST_JWKS).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global PRE_SIGNED_INDEX
        if self.path == "/token":
            content_len = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_len).decode("utf-8") if content_len else ""
            
            # Extract code from body if present
            code = "default"
            for part in post_body.split("&"):
                if part.startswith("code="):
                    code = part.split("=")[1]

            if "returning" in code:
                id_token = PRE_SIGNED_RETURNING_TOKEN
            else:
                PRE_SIGNED_INDEX = (PRE_SIGNED_INDEX + 1) % len(PRE_SIGNED_NEW_TOKENS)
                id_token = PRE_SIGNED_NEW_TOKENS[PRE_SIGNED_INDEX]

            response_data = {
                "id_token": id_token,
                "access_token": "mock_access_token_abc123",
                "token_type": "Bearer",
                "expires_in": 3600,
            }
            body = json.dumps(response_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

def run_mock_server(port=8010):
    server = ThreadingHTTPServer(("127.0.0.1", port), MockOAuthHandler)
    server.serve_forever()

if __name__ == "__main__":
    run_mock_server()
