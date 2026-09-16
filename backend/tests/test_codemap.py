from __future__ import annotations

from pathlib import Path

from app.parsing.builder import build_codemap, load_codemap, save_codemap
from app.pipeline.scan import scan_project


def _mk(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


PY_PROJECT = {
    "app/__init__.py": "",
    "app/main.py": '''from flask import Flask
from app.services import create_user, get_user
from . import db

app = Flask(__name__)

@app.route("/users", methods=["POST"])
def register():
    """Register a new user."""
    data = request.json
    user = create_user(data["email"], data["password"])
    return jsonify(user)

@app.route("/users/<int:uid>")
def show(uid):
    return jsonify(get_user(uid))

def main():
    db.init()
    app.run(port=5000)

if __name__ == "__main__":
    main()
''',
    "app/services.py": '''from app.db import save, load
import hashlib

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def create_user(email, password):
    """Create and save a user."""
    record = {"email": email, "pw": hash_password(password)}
    if not email:
        raise ValueError("email required")
    save("users", record)
    return record

def get_user(uid):
    return load("users", uid)
''',
    "app/db.py": """STORE = {}

def init():
    STORE.clear()

def save(table, record):
    STORE.setdefault(table, []).append(record)

def load(table, uid):
    return STORE.get(table, [])[uid]

class Repo:
    def get_name(self):
        return self.name
""",
    "README.md": "# Users API\n",
}


def test_build_python_codemap(tmp_path: Path) -> None:
    _mk(tmp_path, PY_PROJECT)
    scan = scan_project(tmp_path)
    cm = build_codemap(tmp_path, scan)
    stats = cm.stats()
    assert stats["files"] == 4 and stats["classes"] == 1
    register = cm.symbols["app/main.py::register"]
    assert register.decorators == ['app.route("/users", methods=["POST"])']
    assert register.docstring == "Register a new user."
    create = cm.symbols["app/services.py::create_user"]
    # cross-file resolution via "from app.services import create_user"
    assert any(c.resolved == create.id for c in register.calls)
    # intra-file resolution
    assert any(c.resolved == "app/services.py::hash_password" for c in create.calls)
    # resolution through "from app.db import save"
    assert any(c.resolved == "app/db.py::save" for c in create.calls)
    # module alias: "from . import db" then db.init()
    main = cm.symbols["app/main.py::main"]
    assert any(c.resolved == "app/db.py::init" for c in main.calls)
    # unknown stays unknown
    assert any(c.name == "jsonify" and c.resolved is None for c in register.calls)
    imports = {i.module: i.resolved_file for i in cm.files["app/main.py"].imports}
    assert imports["app.services"] == "app/services.py"
    assert imports["."] == "app/__init__.py"
    assert imports["flask"] is None
    kinds = {(e.kind, e.file) for e in cm.entry_points}
    assert ("main_guard", "app/main.py") in kinds
    assert ("route", "app/main.py") in kinds
    assert ("server_start", "app/main.py") in kinds
    assert ("main_function", "app/main.py") in kinds
    # leaf / trivial rules
    assert cm.symbols["app/db.py::Repo.get_name"].is_trivial
    assert cm.symbols["app/db.py::init"].is_leaf
    assert not create.is_trivial
    assert cm.callers_of(create.id)[0].id == register.id
    save_codemap(cm, tmp_path)
    loaded = load_codemap(tmp_path)
    assert loaded is not None and loaded.stats() == stats


JS_PROJECT = {
    "package.json": '{"main": "src/server.js", "dependencies": {"express": "4"}}',
    "src/server.js": """const express = require('express');
const { listOrders, createOrder } = require('./orders');
const app = express();
app.get('/orders', async (req, res) => { res.json(await listOrders()); });
app.post('/orders', createOrder);
app.listen(3000);
""",
    "src/orders.js": """const db = require('./db');
async function listOrders() { return db.query('select * from orders'); }
async function createOrder(req, res) {
  const order = await db.insert('orders', req.body);
  res.status(201).json(order);
}
module.exports = { listOrders, createOrder };
""",
    "src/db.js": """const pool = {};
exports.query = async function (sql) { return pool.run(sql); };
exports.insert = async (table, row) => { return pool.run(table, row); };
""",
}


def test_build_js_codemap(tmp_path: Path) -> None:
    _mk(tmp_path, JS_PROJECT)
    scan = scan_project(tmp_path)
    cm = build_codemap(tmp_path, scan)
    assert set(cm.symbols) >= {
        "src/orders.js::listOrders",
        "src/orders.js::createOrder",
        "src/db.js::query",
        "src/db.js::insert",
    }
    lo = cm.symbols["src/orders.js::listOrders"]
    assert any(c.resolved == "src/db.js::query" for c in lo.calls)
    imports = {i.module: i.resolved_file for i in cm.files["src/server.js"].imports}
    assert imports["./orders"] == "src/orders.js" and imports["express"] is None
    kinds = {(e.kind, e.file, e.symbol_id) for e in cm.entry_points}
    assert ("route", "src/server.js", "src/orders.js::createOrder") in kinds
    assert ("server_start", "src/server.js", None) in kinds
    assert any(k == "manifest:package_main" and f == "src/server.js" for k, f, _ in kinds)
