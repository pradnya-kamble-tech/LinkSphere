import inspect
import os
import sys

backend_dir = os.path.abspath(".")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if "ENVIRONMENT" not in os.environ:
    os.environ["ENVIRONMENT"] = "test"
from app.main import app

routes_list = []

def extract_routes(app_or_router, prefix=""):
    for r in getattr(app_or_router, "routes", []):
        cls_name = r.__class__.__name__
        if cls_name == "_IncludedRouter":
            sub_router = getattr(r, "original_router", None)
            inc_ctx = getattr(r, "include_context", None)
            sub_prefix = getattr(inc_ctx, "prefix", "") if inc_ctx else ""
            extract_routes(sub_router, prefix=prefix + sub_prefix)
        elif hasattr(r, "path"):
            full_path = prefix + r.path
            # Normalize double slashes
            while "//" in full_path:
                full_path = full_path.replace("//", "/")
            endpoint = getattr(r, "endpoint", None)
            name = endpoint.__name__ if endpoint else ""
            is_async = inspect.iscoroutinefunction(endpoint) if endpoint else False
            methods = sorted([m for m in getattr(r, "methods", []) if m])
            routes_list.append({
                "methods": ",".join(methods),
                "path": full_path,
                "name": name,
                "kind": "async" if is_async else "sync",
            })

extract_routes(app)

print(f"{'METHODS':<12} | {'PATH':<35} | {'FUNCTION NAME':<30} | {'KIND':<6} | {'NOTES'}")
print("-" * 115)
for r in routes_list:
    notes = ""
    if r["path"].startswith("/api/diagnostic"):
        notes = "gated to ENVIRONMENT=test"
    elif r["path"] in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
        notes = "FastAPI default docs"
    print(f"{r['methods']:<12} | {r['path']:<35} | {r['name']:<30} | {r['kind']:<6} | {notes}")
