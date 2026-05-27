import sys; sys.path.insert(0, "/app")
import db_manager as db
keys = sorted(db.list_keys(), key=lambda k: k["key"])
for k in keys:
    if not k["key"].startswith("_"):
        print(f"{k['key']:<35} {k.get('last_updated', '-')}")
