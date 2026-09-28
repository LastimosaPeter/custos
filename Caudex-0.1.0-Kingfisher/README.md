# Caudex IDE 0.1.0 — Kingfisher

**Caudex IDE** is a local-first prototype of a small-room collaborative C++ environment designed for students who may be coding from an iPhone, iPad, or Android device instead of a laptop.

This build is intentionally separate from Custos, but its visual language now follows the same compact, responsive system more closely: the supplied 1920×1080 Caudex background, the compact Custos-style version footer, green/tinted surfaces instead of an all-white interface, dark mode, safe-area support, and a focused classroom workflow. The interface requests Gotham as its UI typeface; the editor/console uses JetBrains Mono.

## What Kingfisher already does

- **2–4 simultaneous active users** in one room.
- Shared C++ source using a lightweight **character CRDT**, so concurrent inserts/deletes merge instead of using simple last-write-wins replacement.
- Every user chooses a **caret/pointer color** when joining.
- Live remote caret positions and remote pointer indicators.
- Four share-link roles:
  - **View** — can see source and shared compiler output.
  - **Comment** — View + room chat.
  - **Run** — Comment + compile/run the current shared program, but cannot edit it.
  - **Edit** — full source editing, run, chat, and shared Jam Board access.
- **C++17 compiler** through a local `g++` runner.
- Shared compiler output: when one allowed user runs code, everyone in the room sees the result.
- Persistent room chat in the database.
- Shared touch/stylus **Jam Board** with pen, highlighter, eraser, and clear.
- `.cpp` import/export.
- Mobile coding accessory row for `#include`, `using`, indentation, braces, parentheses, semicolon, stream operators, quotes, and newline.
- JetBrains Mono source editor with lightweight client-side C++ syntax colouring for keywords, types, strings, numbers, comments, preprocessor directives, functions, operators, and literals.
- PWA metadata, iOS/iPadOS safe-area handling, light/dark themes.
- Browser-local pending edit queue. If the socket drops while the room remains open, edits stay usable and merge back when the room reconnects.
- **Offline Solo** page with browser-saved C++ source, `.cpp` import/export, and compilation whenever the Caudex server is reachable.
- Optional **Focus Mode**: desktop fullscreen when supported and logging of hidden-page/fullscreen-exit events. On iOS/iPadOS, installed Home Screen mode is the closest browser-supported equivalent.
- PostgreSQL-ready, with SQLite as the zero-setup local fallback.

## Important limits in this prototype

### 1. The local compiler is not a production sandbox

`code_runner.py` uses time/resource limits and blocks several obvious OS/file/network APIs, but **this is not equivalent to isolated code execution**. A determined user can potentially escape simple source filtering.

Use the included local compiler only for development or a trusted classroom LAN. Before putting Caudex on the public internet, move compilation to an isolated service such as Judge0 or a hardened Docker/container runner with no network, strict CPU/RAM/PID limits, a read-only filesystem, and disposable per-run containers.

### 2. Focus mode cannot truly lock an iPhone/iPad

A web application cannot prevent a student from leaving Safari or switching apps. Caudex can detect/log some page-visibility changes and can request fullscreen on compatible browsers. For iOS/iPadOS, installing the PWA to the Home Screen gives a cleaner standalone UI, but it is not an OS-level kiosk lock.

### 3. “Offline room collaboration” means connection-loss continuation

When an already-open room loses its socket connection, Edit users can keep typing; CRDT operations are stored in the browser and resent after reconnection. A live multi-user room still requires the Flask server. For truly disconnected use, use **Offline Solo**, then export/import the `.cpp` file later.

---

# Quick start on Windows

## A. Install Python

Install Python 3.11+ and make sure the `py` launcher works in Command Prompt or PowerShell.

## B. Install a C++ compiler

Install **MinGW-w64 / MSYS2 g++** and make sure this command works:

```powershell
g++ --version
```

If your compiler command is different, change `CXX=` in `.env`.

## C. Start Caudex

Double-click:

```text
run_local.bat
```

The first run creates a virtual environment, installs Python packages, initializes the local SQLite database, and starts the server.

Then open:

```text
http://127.0.0.1:5000
```

---

# Quick start on macOS / Linux

Make sure Python and a C++17 compiler are installed. On macOS you may use `clang++`; set `CXX=clang++` in `.env`.

```bash
chmod +x run_local.sh
./run_local.sh
```

Open:

```text
http://127.0.0.1:5000
```

---

# Let phones and iPads join on the same Wi-Fi

Caudex listens on `0.0.0.0` by default. Keep the computer running Caudex and the students’ devices on the **same local network**.

1. Create a room on the computer.
2. Click **Share Room**.
3. Copy the appropriate View / Comment / Run / Edit link.
4. Send that link to the student.
5. The generated local share links attempt to use the host computer’s LAN IP instead of `localhost`.

If a phone cannot open the link, check Windows Firewall and allow Python for **Private networks**. School Wi-Fi may also use client isolation; if devices cannot reach each other, a personal hotspot or a deployed server may be required.

---

# Database choices

## Default: SQLite

Leave `DATABASE_URL` blank in `.env`:

```env
DATABASE_URL=
```

Caudex stores its development database at:

```text
instance/caudex.db
```

## PostgreSQL

A `docker-compose.yml` is included for local PostgreSQL:

```bash
docker compose up -d postgres
```

Then set:

```env
DATABASE_URL=postgresql+psycopg://caudex:caudex@localhost:5432/caudex
```

Restart Caudex. The tables are created automatically in this prototype.

---

# Environment variables

Copy `.env.example` to `.env` if you are not using the helper scripts.

```env
SECRET_KEY=replace-this
DATABASE_URL=
HOST=0.0.0.0
PORT=5000
FLASK_DEBUG=0
CAUDEX_RUNNER_BACKEND=local
CXX=g++
PUBLIC_BASE_URL=
```

Set `CAUDEX_RUNNER_BACKEND=disabled` when you want editing/collaboration without local execution.

After deployment, set `PUBLIC_BASE_URL` to your HTTPS domain so generated invitation links use the correct public host.

---

# Mobile design notes

The phone layout intentionally prioritizes **writing C++**, not dashboards:

- Code takes the center of the screen.
- People and chat become side drawers.
- Run / Chat / Import / Export stay in a bottom action bar.
- Common C++ symbols/snippets are one tap above the editor.
- `autocapitalize`, autocorrect, and spellcheck are disabled for source input.
- The editor uses **JetBrains Mono**, syntax colouring, and horizontally scrolls inside the editor instead of wrapping code. The page itself is constrained to the viewport and does not horizontally scroll.
- iOS safe-area insets are respected around the status bar and Home indicator.

On iPad landscape, the layout moves closer to the desktop three-column workspace.

---

# GitHub-ready workflow

Before your first commit:

```bash
git init
git add -A
git commit -m "Initial Caudex IDE 0.1.0 Kingfisher prototype"
```

`.gitignore` already excludes `.env`, local virtual environments, Python caches, and the SQLite database.

Do **not** commit real secrets or production database credentials.

---

# Suggested next versions

The current bird codename is **Kingfisher**. Future releases can continue the bird naming rule, for example: Kestrel, Heron, Osprey, Tern, Falcon, or Albatross.

For the next engineering pass, the highest-value items are:

- isolated production runner (Judge0/Docker);
- instructor room dashboard and security-event viewer;
- room expiration/revocation and one-time invite links;
- proper user accounts/ADNU identity;
- line comments anchored to source positions;
- multiple files/tabs instead of only `main.cpp`;
- compile diagnostics mapped to editor line numbers;
- Redis-backed presence/pub-sub for multiple web workers;
- database migrations (Alembic/Flask-Migrate);
- optional room history/snapshots and restore points;
- C/C++ autocomplete using a browser-capable language service.

---

## Release

**Caudex IDE · v0.1.0 · *Alcedo atthis* (Kingfisher)**


### Typeface note

Caudex does not bundle proprietary font files. The UI CSS requests **Gotham** first, so a locally installed/licensed Gotham family will be used automatically; a standard sans-serif fallback is used when Gotham is not available. JetBrains Mono is requested from Google Fonts for the coding surface, with local monospace fallbacks.
