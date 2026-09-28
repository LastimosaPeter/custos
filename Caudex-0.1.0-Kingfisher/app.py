from __future__ import annotations

import json
import os
import secrets
import socket
import string
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_sock import Sock
from flask_sqlalchemy import SQLAlchemy

from code_runner import run_cpp

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_database_url(value: str | None) -> str:
    if not value:
        return f"sqlite:///{BASE_DIR / 'instance' / 'caudex.db'}"
    # Render/Heroku-style URLs may still use the old postgres:// prefix.
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    if value.startswith("postgresql://") and "+psycopg" not in value:
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


app = Flask(__name__, instance_relative_config=True)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
    SQLALCHEMY_DATABASE_URI=normalize_database_url(os.getenv("DATABASE_URL")),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=1_000_000,
)
Path(app.instance_path).mkdir(parents=True, exist_ok=True)

db = SQLAlchemy(app)
sock = Sock(app)

APP_VERSION = "0.1.0"
APP_CODENAME = "Kingfisher"
APP_RELEASE_SPECIES = "Alcedo atthis"
APP_RELEASE_COMMON_NAME = "Common Kingfisher"
ROOT_NODE = "__ROOT__"
MAX_SOURCE_CHARS = 100_000
MAX_CHAT_CHARS = 2_000
MAX_WHITEBOARD_STROKES = 1_500
VALID_ROLES = {"view", "comment", "run", "edit"}
ROLE_CAPABILITIES = {
    "view": {"view": True, "comment": False, "run": False, "edit": False},
    "comment": {"view": True, "comment": True, "run": False, "edit": False},
    "run": {"view": True, "comment": True, "run": True, "edit": False},
    "edit": {"view": True, "comment": True, "run": True, "edit": True},
}


class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(12), unique=True, nullable=False, index=True)
    title = db.Column(db.String(100), nullable=False, default="Untitled C++ Room")
    max_users = db.Column(db.Integer, nullable=False, default=4)
    focus_mode = db.Column(db.Boolean, nullable=False, default=False)
    source_code = db.Column(db.Text, nullable=False, default="")
    crdt_json = db.Column(db.Text, nullable=False, default="{}")
    whiteboard_json = db.Column(db.Text, nullable=False, default="[]")
    revision = db.Column(db.Integer, nullable=False, default=0)
    last_run_json = db.Column(db.Text, nullable=False, default="{}")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Participant(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False, index=True)
    display_name = db.Column(db.String(60), nullable=False)
    color = db.Column(db.String(16), nullable=False, default="#5FBB7A")
    role = db.Column(db.String(16), nullable=False, default="view")
    is_host = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    room = db.relationship("Room", backref=db.backref("participants", lazy=True))


class AccessLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False, index=True)
    role = db.Column(db.String(16), nullable=False)
    token = db.Column(db.String(96), unique=True, nullable=False, index=True)
    room = db.relationship("Room", backref=db.backref("access_links", lazy=True, cascade="all, delete-orphan"))


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False, index=True)
    participant_id = db.Column(db.String(36), nullable=True)
    display_name = db.Column(db.String(60), nullable=False)
    color = db.Column(db.String(16), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class SecurityEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey("room.id"), nullable=False, index=True)
    participant_id = db.Column(db.String(36), nullable=False)
    event_type = db.Column(db.String(40), nullable=False)
    details = db.Column(db.String(240), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


def generate_room_code(length: int = 6) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not Room.query.filter_by(code=code).first():
            return code


def sanitize_color(value: str | None) -> str:
    value = (value or "").strip().upper()
    if len(value) == 7 and value.startswith("#") and all(c in string.hexdigits for c in value[1:]):
        return value
    return "#5FBB7A"


def sanitize_name(value: str | None) -> str:
    value = " ".join((value or "").strip().split())
    return value[:60] or "Coder"


def default_cpp() -> str:
    return (
        "#include <iostream>\n"
        "using namespace std;\n\n"
        "int main() {\n"
        "    cout << \"Hello, Caudex!\" << endl;\n"
        "    return 0;\n"
        "}\n"
    )


def make_crdt(text: str) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    previous = ROOT_NODE
    for index, char in enumerate(text):
        node_id = f"seed:{index:08d}"
        nodes[node_id] = {
            "id": node_id,
            "after": previous,
            "ch": char,
            "deleted": False,
        }
        previous = node_id
    return {"nodes": nodes}


def normalize_crdt(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            data = {}
    elif isinstance(raw, dict):
        data = raw
    else:
        data = {}
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        nodes = {}
    clean: dict[str, dict[str, Any]] = {}
    for node_id, node in nodes.items():
        if not isinstance(node_id, str) or not isinstance(node, dict):
            continue
        ch = node.get("ch", "")
        after = node.get("after", ROOT_NODE)
        if not isinstance(ch, str) or len(ch) != 1 or not isinstance(after, str):
            continue
        clean[node_id] = {
            "id": node_id,
            "after": after,
            "ch": ch,
            "deleted": bool(node.get("deleted", False)),
        }
    return {"nodes": clean}


def crdt_order(crdt: dict[str, Any]) -> list[str]:
    nodes = crdt.get("nodes", {})
    children: dict[str, list[str]] = defaultdict(list)
    for node_id, node in nodes.items():
        after = node.get("after", ROOT_NODE)
        if after != ROOT_NODE and after not in nodes:
            after = ROOT_NODE
        children[after].append(node_id)
    for child_list in children.values():
        child_list.sort()

    order: list[str] = []
    stack = list(reversed(children.get(ROOT_NODE, [])))
    visited: set[str] = set()
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        order.append(node_id)
        for child in reversed(children.get(node_id, [])):
            stack.append(child)
    # Orphan/cyclic nodes are appended deterministically rather than discarded.
    for node_id in sorted(nodes):
        if node_id not in visited:
            order.append(node_id)
    return order


def crdt_text(crdt: dict[str, Any]) -> str:
    nodes = crdt.get("nodes", {})
    chars: list[str] = []
    for node_id in crdt_order(crdt):
        node = nodes[node_id]
        if not node.get("deleted"):
            chars.append(node.get("ch", ""))
    return "".join(chars)


def safe_json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return fallback


def current_participant_for_room(room: Room) -> Participant | None:
    participant_id = session.get("participant_id")
    if not participant_id:
        return None
    participant = db.session.get(Participant, participant_id)
    if not participant or participant.room_id != room.id:
        return None
    return participant


def local_ip() -> str:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def share_base_url() -> str:
    configured = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if configured:
        return configured
    host = request.host.split(":")[0]
    port = request.host.split(":", 1)[1] if ":" in request.host else ""
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        host = local_ip()
    scheme = "https" if request.is_secure else "http"
    return f"{scheme}://{host}{':' + port if port else ''}"


def serialize_participant(participant: Participant, active: bool = True) -> dict[str, Any]:
    return {
        "id": participant.id,
        "name": participant.display_name,
        "color": participant.color,
        "role": participant.role,
        "is_host": participant.is_host,
        "active": active,
    }


@app.context_processor
def inject_app_info() -> dict[str, Any]:
    return {"app_version": APP_VERSION, "app_codename": APP_CODENAME, "app_release_species": APP_RELEASE_SPECIES, "app_release_common_name": APP_RELEASE_COMMON_NAME}


@app.route("/")
def index():
    return render_template("index.html")


@app.post("/rooms")
def create_room():
    title = " ".join((request.form.get("title") or "").strip().split())[:100] or "Untitled C++ Room"
    name = sanitize_name(request.form.get("name"))
    color = sanitize_color(request.form.get("color"))
    try:
        max_users = int(request.form.get("max_users") or 4)
    except ValueError:
        max_users = 4
    max_users = min(4, max(2, max_users))
    focus_mode = request.form.get("focus_mode") == "1"
    code = generate_room_code()
    source = default_cpp()
    room = Room(
        code=code,
        title=title,
        max_users=max_users,
        focus_mode=focus_mode,
        source_code=source,
        crdt_json=json.dumps(make_crdt(source), separators=(",", ":")),
        whiteboard_json="[]",
    )
    db.session.add(room)
    db.session.flush()

    for role in ("view", "comment", "run", "edit"):
        db.session.add(AccessLink(room_id=room.id, role=role, token=secrets.token_urlsafe(32)))

    participant = Participant(
        id=str(uuid.uuid4()),
        room_id=room.id,
        display_name=name,
        color=color,
        role="edit",
        is_host=True,
    )
    db.session.add(participant)
    db.session.commit()
    session.clear()
    session["participant_id"] = participant.id
    return redirect(url_for("workspace", code=room.code))


@app.route("/join/<code>/<token>", methods=["GET", "POST"])
def join_room(code: str, token: str):
    room = Room.query.filter_by(code=code.upper()).first_or_404()
    link = AccessLink.query.filter_by(room_id=room.id, token=token).first()
    if not link:
        abort(404)
    if request.method == "POST":
        participant = Participant(
            id=str(uuid.uuid4()),
            room_id=room.id,
            display_name=sanitize_name(request.form.get("name")),
            color=sanitize_color(request.form.get("color")),
            role=link.role,
            is_host=False,
        )
        db.session.add(participant)
        db.session.commit()
        session.clear()
        session["participant_id"] = participant.id
        return redirect(url_for("workspace", code=room.code))
    return render_template("join.html", room=room, role=link.role, token=token)


@app.route("/r/<code>")
def workspace(code: str):
    room = Room.query.filter_by(code=code.upper()).first_or_404()
    participant = current_participant_for_room(room)
    if not participant:
        return redirect(url_for("index"))
    participant.last_seen_at = utcnow()
    db.session.commit()

    links: dict[str, str] = {}
    if participant.is_host:
        base = share_base_url()
        for link in room.access_links:
            links[link.role] = f"{base}{url_for('join_room', code=room.code, token=link.token)}"

    capabilities = ROLE_CAPABILITIES.get(participant.role, ROLE_CAPABILITIES["view"])
    return render_template(
        "workspace.html",
        room=room,
        participant=participant,
        capabilities=capabilities,
        links=links,
    )


@app.route("/offline")
def offline_editor():
    return render_template("offline.html")


@app.post("/api/rooms/<code>/run")
def api_run_room(code: str):
    room = Room.query.filter_by(code=code.upper()).first_or_404()
    participant = current_participant_for_room(room)
    if not participant:
        return jsonify({"ok": False, "status": "unauthorized", "message": "Join the room first."}), 401
    caps = ROLE_CAPABILITIES.get(participant.role, ROLE_CAPABILITIES["view"])
    if not caps["run"]:
        return jsonify({"ok": False, "status": "forbidden", "message": "This link cannot run code."}), 403
    payload = request.get_json(silent=True) or {}
    stdin_text = str(payload.get("stdin") or "")[:20_000]
    source_to_run = room.source_code
    if caps["edit"] and isinstance(payload.get("source"), str):
        source_to_run = str(payload.get("source"))[:MAX_SOURCE_CHARS]
    result = run_cpp(source_to_run, stdin_text)
    shared_result = dict(result)
    shared_result["by"] = participant.display_name
    shared_result["by_id"] = participant.id
    shared_result["created_at"] = utcnow().isoformat()
    room.last_run_json = json.dumps(shared_result, separators=(",", ":"), ensure_ascii=False)
    db.session.commit()
    try:
        broadcast(room.code, {"type": "run_result", "result": shared_result})
    except Exception:
        pass
    return jsonify(result)


@app.post("/api/solo/run")
def api_run_solo():
    payload = request.get_json(silent=True) or {}
    source = str(payload.get("source") or "")[:MAX_SOURCE_CHARS]
    stdin_text = str(payload.get("stdin") or "")[:20_000]
    return jsonify(run_cpp(source, stdin_text))


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest", mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/health")
def health():
    return jsonify({"ok": True, "product": "Caudex IDE", "version": APP_VERSION, "codename": APP_CODENAME})


# ----------------------------
# Native WebSocket collaboration
# ----------------------------
ROOM_CONNECTIONS: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
ROOM_LOCK = threading.RLock()


def active_participant_ids(room_code: str) -> set[str]:
    with ROOM_LOCK:
        return {entry["participant_id"] for entry in ROOM_CONNECTIONS.get(room_code, {}).values()}


def connection_payload_presence(room: Room) -> list[dict[str, Any]]:
    active = active_participant_ids(room.code)
    if not active:
        return []
    participants = Participant.query.filter(Participant.id.in_(active)).all()
    return [serialize_participant(p, True) for p in participants]


def safe_send(entry: dict[str, Any], payload: dict[str, Any]) -> bool:
    try:
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with entry["send_lock"]:
            entry["ws"].send(text)
        return True
    except Exception:
        return False


def broadcast(room_code: str, payload: dict[str, Any], exclude_conn_id: str | None = None) -> None:
    stale: list[str] = []
    with ROOM_LOCK:
        entries = list(ROOM_CONNECTIONS.get(room_code, {}).items())
    for conn_id, entry in entries:
        if exclude_conn_id and conn_id == exclude_conn_id:
            continue
        if not safe_send(entry, payload):
            stale.append(conn_id)
    if stale:
        with ROOM_LOCK:
            for conn_id in stale:
                ROOM_CONNECTIONS.get(room_code, {}).pop(conn_id, None)


def validate_and_apply_crdt(room: Room, inserts: Any, deletes: Any) -> tuple[dict[str, Any], str] | None:
    if not isinstance(inserts, list) or not isinstance(deletes, list):
        return None
    if len(inserts) > 5_000 or len(deletes) > 5_000:
        return None

    crdt = normalize_crdt(room.crdt_json)
    nodes = crdt["nodes"]
    clean_inserts: list[dict[str, Any]] = []
    clean_deletes: list[str] = []

    for item in inserts:
        if not isinstance(item, dict):
            return None
        node_id = item.get("id")
        after = item.get("after")
        ch = item.get("ch")
        if not isinstance(node_id, str) or not node_id or len(node_id) > 120:
            return None
        if node_id in nodes:
            # Idempotent re-send.
            continue
        if not isinstance(after, str) or (after != ROOT_NODE and after not in nodes and not any(x.get("id") == after for x in clean_inserts)):
            return None
        if not isinstance(ch, str) or len(ch) != 1:
            return None
        clean = {"id": node_id, "after": after, "ch": ch, "deleted": False}
        clean_inserts.append(clean)
        nodes[node_id] = clean

    for node_id in deletes:
        if not isinstance(node_id, str) or node_id not in nodes:
            continue
        nodes[node_id]["deleted"] = True
        clean_deletes.append(node_id)

    source = crdt_text(crdt)
    if len(source) > MAX_SOURCE_CHARS:
        return None
    room.crdt_json = json.dumps(crdt, separators=(",", ":"), ensure_ascii=False)
    room.source_code = source
    room.revision += 1
    return {"inserts": clean_inserts, "deletes": clean_deletes}, source


@sock.route("/ws/<code>")
def room_socket(ws, code: str):
    code = code.upper()
    room = Room.query.filter_by(code=code).first()
    if not room:
        try:
            ws.send(json.dumps({"type": "fatal", "message": "Room not found."}))
        finally:
            return
    participant = current_participant_for_room(room)
    if not participant:
        try:
            ws.send(json.dumps({"type": "fatal", "message": "Join this room before connecting."}))
        finally:
            return

    conn_id = secrets.token_urlsafe(12)
    with ROOM_LOCK:
        existing_active = active_participant_ids(code)
        if participant.id not in existing_active and len(existing_active) >= room.max_users:
            ws.send(json.dumps({"type": "fatal", "message": f"This room already has {room.max_users} active users."}))
            return
        ROOM_CONNECTIONS[code][conn_id] = {
            "ws": ws,
            "participant_id": participant.id,
            "send_lock": threading.Lock(),
        }

    try:
        participant.last_seen_at = utcnow()
        db.session.commit()
        recent_chat = (
            ChatMessage.query.filter_by(room_id=room.id)
            .order_by(ChatMessage.id.desc())
            .limit(80)
            .all()
        )
        recent_chat.reverse()
        security_counts = dict(
            db.session.query(SecurityEvent.participant_id, db.func.count(SecurityEvent.id))
            .filter(SecurityEvent.room_id == room.id)
            .group_by(SecurityEvent.participant_id)
            .all()
        )
        hello = {
            "type": "hello",
            "room": {
                "code": room.code,
                "title": room.title,
                "focus_mode": room.focus_mode,
                "revision": room.revision,
                "max_users": room.max_users,
            },
            "you": serialize_participant(participant),
            "capabilities": ROLE_CAPABILITIES.get(participant.role, ROLE_CAPABILITIES["view"]),
            "crdt": normalize_crdt(room.crdt_json),
            "whiteboard": safe_json_loads(room.whiteboard_json, []),
            "chat": [
                {
                    "id": m.id,
                    "participant_id": m.participant_id,
                    "name": m.display_name,
                    "color": m.color,
                    "body": m.body,
                    "created_at": m.created_at.isoformat() if m.created_at else "",
                }
                for m in recent_chat
            ],
            "security_counts": security_counts,
            "last_run": safe_json_loads(room.last_run_json, {}),
        }
        ws.send(json.dumps(hello, separators=(",", ":"), ensure_ascii=False))
        broadcast(code, {"type": "presence", "participants": connection_payload_presence(room)})

        while True:
            raw = ws.receive()
            if raw is None:
                break
            try:
                message = json.loads(raw)
            except Exception:
                continue
            if not isinstance(message, dict):
                continue
            msg_type = message.get("type")
            participant = db.session.get(Participant, participant.id)
            room = db.session.get(Room, room.id)
            if not participant or not room:
                break
            caps = ROLE_CAPABILITIES.get(participant.role, ROLE_CAPABILITIES["view"])

            if msg_type == "crdt_op" and caps["edit"]:
                applied = validate_and_apply_crdt(room, message.get("inserts"), message.get("deletes"))
                if not applied:
                    safe_send(ROOM_CONNECTIONS[code][conn_id], {"type": "source_resync", "crdt": normalize_crdt(room.crdt_json), "revision": room.revision})
                    continue
                clean_op, _ = applied
                db.session.commit()
                broadcast(
                    code,
                    {
                        "type": "crdt_op",
                        "participant_id": participant.id,
                        "revision": room.revision,
                        "op_id": str(message.get("op_id") or "")[:120],
                        "inserts": clean_op["inserts"],
                        "deletes": clean_op["deletes"],
                    },
                )

            elif msg_type == "cursor":
                payload = {
                    "type": "cursor",
                    "participant_id": participant.id,
                    "line": max(0, min(100_000, int(message.get("line") or 0))),
                    "visual_col": max(0, min(10_000, int(message.get("visual_col") or 0))),
                    "selection": bool(message.get("selection")),
                }
                broadcast(code, payload, exclude_conn_id=conn_id)

            elif msg_type == "pointer":
                try:
                    x = max(0.0, min(1.0, float(message.get("x") or 0)))
                    y = max(0.0, min(1.0, float(message.get("y") or 0)))
                except Exception:
                    continue
                broadcast(code, {"type": "pointer", "participant_id": participant.id, "x": x, "y": y}, exclude_conn_id=conn_id)

            elif msg_type == "chat" and caps["comment"]:
                body = str(message.get("body") or "").strip()[:MAX_CHAT_CHARS]
                if not body:
                    continue
                chat = ChatMessage(
                    room_id=room.id,
                    participant_id=participant.id,
                    display_name=participant.display_name,
                    color=participant.color,
                    body=body,
                )
                db.session.add(chat)
                db.session.commit()
                broadcast(
                    code,
                    {
                        "type": "chat",
                        "message": {
                            "id": chat.id,
                            "participant_id": participant.id,
                            "name": participant.display_name,
                            "color": participant.color,
                            "body": body,
                            "created_at": chat.created_at.isoformat() if chat.created_at else "",
                        },
                    },
                )

            elif msg_type == "whiteboard_stroke" and caps["edit"]:
                stroke = message.get("stroke")
                if not isinstance(stroke, dict):
                    continue
                points = stroke.get("points")
                if not isinstance(points, list) or not points or len(points) > 3_000:
                    continue
                clean_points = []
                for point in points:
                    if not isinstance(point, list) or len(point) != 2:
                        continue
                    try:
                        px = max(0.0, min(1.0, float(point[0])))
                        py = max(0.0, min(1.0, float(point[1])))
                    except Exception:
                        continue
                    clean_points.append([round(px, 5), round(py, 5)])
                if not clean_points:
                    continue
                tool = str(stroke.get("tool") or "pen")
                if tool not in {"pen", "highlighter", "eraser"}:
                    tool = "pen"
                clean_stroke = {
                    "id": str(stroke.get("id") or secrets.token_urlsafe(8))[:80],
                    "participant_id": participant.id,
                    "color": sanitize_color(stroke.get("color")),
                    "width": max(1, min(40, int(stroke.get("width") or 3))),
                    "tool": tool,
                    "points": clean_points,
                }
                strokes = safe_json_loads(room.whiteboard_json, [])
                if not isinstance(strokes, list):
                    strokes = []
                strokes.append(clean_stroke)
                if len(strokes) > MAX_WHITEBOARD_STROKES:
                    strokes = strokes[-MAX_WHITEBOARD_STROKES:]
                room.whiteboard_json = json.dumps(strokes, separators=(",", ":"))
                db.session.commit()
                broadcast(code, {"type": "whiteboard_stroke", "stroke": clean_stroke})

            elif msg_type == "whiteboard_clear" and caps["edit"]:
                room.whiteboard_json = "[]"
                db.session.commit()
                broadcast(code, {"type": "whiteboard_clear", "participant_id": participant.id})

            elif msg_type == "security_event" and room.focus_mode:
                event_type = str(message.get("event_type") or "focus_change")[:40]
                details = str(message.get("details") or "")[:240]
                event = SecurityEvent(
                    room_id=room.id,
                    participant_id=participant.id,
                    event_type=event_type,
                    details=details,
                )
                db.session.add(event)
                db.session.commit()
                count = SecurityEvent.query.filter_by(room_id=room.id, participant_id=participant.id).count()
                broadcast(code, {"type": "security_count", "participant_id": participant.id, "count": count})

            elif msg_type == "ping":
                participant.last_seen_at = utcnow()
                db.session.commit()
                safe_send(ROOM_CONNECTIONS[code][conn_id], {"type": "pong"})

    finally:
        with ROOM_LOCK:
            ROOM_CONNECTIONS.get(code, {}).pop(conn_id, None)
            if not ROOM_CONNECTIONS.get(code):
                ROOM_CONNECTIONS.pop(code, None)
        try:
            room = Room.query.filter_by(code=code).first()
            if room:
                broadcast(code, {"type": "presence", "participants": connection_payload_presence(room)})
        except Exception:
            pass


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug, threaded=True)
