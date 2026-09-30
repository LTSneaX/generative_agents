# Generative Agents — Security Review

**Date:** 30 September 2026 · **Revision reviewed:** `main` after merge `36ea0d11` (code identical to `fe05a71d`)
**Scope:** the Django environment server (`environment/frontend_server`), the simulation server
(`reverie/backend_server`), the browser code in `templates/`, configuration, secrets, and dependencies.
**Method:** reading every Python view, setting and template that handles outside input; tracing where
text from the language model ends up; checking dependency ages; and running the app locally (see
`docs/hands-on-test-2026-09-30/REPORT.md`).

---

## How to read this report

Generative Agents is a **research project meant to run on one person's own computer**. The web server
is started with `python manage.py runserver`, which by default only listens on `127.0.0.1` (your own
machine). Most of the issues below are therefore **low risk as long as you keep it that way**, and
**serious the moment the server is reachable by anyone else**: on a shared lab machine, a cloud VM
with an open port, a university server, or when someone runs `runserver 0.0.0.0:8000` to show a
colleague.

People regularly do exactly that with research demos, so each finding says:

* **What** the problem is, in plain words.
* **Where** it is (file and line).
* **Why** it matters, and **when** it actually bites you.
* **How** to fix it, with the smallest safe change.

Severity uses two numbers: how bad it is **on your own laptop**, and how bad it is **once the
server is reachable by others**.

| Rating | Meaning |
|---|---|
| Critical | Someone else can change or destroy your files or take over the server |
| High | Someone else can read or corrupt data, or the defaults make a serious mistake likely |
| Medium | A real weakness that needs another mistake or a special situation to matter |
| Low | Hygiene; fix when convenient |

---

## Summary table

| # | Finding | Laptop | Exposed |
|---|---|---|---|
| S1 | Server endpoints build file paths from request data with no checks | Low | **Critical** |
| S2 | Cross-site request forgery protection is switched off | Low–Medium | **High** |
| S3 | Model-written text is inserted into the page as HTML | Medium | **High** |
| S4 | The Django secret key is hard-coded and public | Low | **High** |
| S5 | Debug mode is always on | Low | **High** |
| S6 | Django 2.2 and many pinned packages are end-of-life | Low | **High** |
| S7 | Typed simulation names are used to copy and **delete** folders | Medium (data loss) | Medium |
| S8 | The OpenAI key lives in a plain Python file that the code imports | Medium | Medium |
| S9 | Errors from the AI service are silently turned into "normal" text | Low | Low |
| S10 | Third-party files are loaded from outside sites with no integrity checks | Low | Medium |
| S11 | The settings loader falls back to a file that does not exist | Low | Medium |
| S12 | Admin site and an unused database are enabled | Low | Low |

---

## S1 — Server endpoints build file paths from request data with no checks

**Where:** `environment/frontend_server/translator/views.py`
* `process_environment` (lines 241–265) writes to `storage/{sim_code}/environment/{step}.json`
* `update_environment` (lines 268–295) reads `storage/{sim_code}/movement/{step}.json`
* both take `sim_code` and `step` from the JSON body of the request

**What is going on:** these two endpoints are how the browser and the simulation talk to each other.
The browser sends a small JSON message, and the server uses two fields from it, `sim_code` and `step`,
to decide which file on disk to read or write. The code pastes those values directly into a file path.

The URL-based pages (`/replay/...`, `/demo/...`) are protected by accident: their URL patterns only
accept letters, numbers, `_` and `-` (`[\w-]+` in `urls.py`), so a URL can't smuggle in characters
that change which folder is used. The two JSON endpoints have **no such filter**. Whatever arrives in
the message body is used as-is.

**Why it matters:** a file path built from untrusted input can point somewhere the programmer never
intended: another folder, a parent folder, or a file with a different name. `process_environment`
**writes** a file, and does so with content that also comes from the request. `update_environment`
**reads** a JSON file and sends its contents back. Together that is a read/write primitive on the
server's disk, limited only by what the Django process is allowed to touch.

**When it bites:** only when someone other than you can send requests to the server (see "How to read
this report"). Because CSRF protection is also off (S2), a web page you visit in another tab can also
send these requests to your local server in some browser configurations.

**How to fix (small):** validate both values before using them, and resolve the final path to make
sure it is inside the storage folder.

```python
import re
from pathlib import Path
from django.http import HttpResponseBadRequest

STORAGE = Path("storage").resolve()
SIM_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

def _sim_path(sim_code, *parts):
    if not isinstance(sim_code, str) or not SIM_CODE_RE.match(sim_code):
        raise ValueError("bad sim_code")
    p = (STORAGE / sim_code).joinpath(*parts).resolve()
    if STORAGE not in p.parents:
        raise ValueError("path escapes storage")
    return p

def process_environment(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST only")
    data = json.loads(request.body)
    try:
        step = int(data["step"])                 # must be a plain number
        target = _sim_path(data["sim_code"], "environment", f"{step}.json")
    except (KeyError, ValueError, TypeError):
        return HttpResponseBadRequest("bad request")
    target.write_text(json.dumps(data["environment"], indent=2))
    return HttpResponse("received")
```

Apply the same `_sim_path` helper in `update_environment`, `replay`, `replay_persona_state`, `demo`
and `home`. `int(step)` alone removes half the problem: a number can't contain a slash.

---

## S2 — Cross-site request forgery (CSRF) protection is switched off

**Where:** `frontend_server/settings/base.py` line 49 and `settings/local.py`
(`# 'django.middleware.csrf.CsrfViewMiddleware',` is commented out).

**What it is:** Django's CSRF protection stops *other websites* from making your browser send
requests to *your* server. Without it, any page open in your browser can quietly send a POST request
to `http://localhost:8000/process_environment/` or `/path_tester_update/`. Your browser attaches no
special permission check, and the server can't tell the request didn't come from the Smallville page.

**Why it was probably turned off:** the simulator pages send JSON with plain `XMLHttpRequest` calls and
don't include Django's CSRF token. Turning the middleware off was the quickest way to make that work.

**When it bites:** any time the server is running and you browse other sites. Browsers do run an extra
permission check before some cross-site requests, but these endpoints parse the body as JSON no matter
what content type the request declares (the simulator page itself sends it with no content type at
all). So a request can be shaped so that the browser sends it without asking first. With endpoints
that write files (S1), that is not a gap to leave open.

**How to fix:** turn the middleware back on and send the token from the pages. Django documents this
exact pattern:

```javascript
// in templates/base.html, once
function getCookie(name) {
  const m = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return m ? m.pop() : '';
}
// on every XMLHttpRequest that POSTs
xobj.setRequestHeader("X-CSRFToken", getCookie("csrftoken"));
```

Add `{% csrf_token %}` once to `base.html` (or use `ensure_csrf_cookie` on the views that render the
simulator) so the cookie exists. Restrict the endpoints to POST with `@require_POST` while you are there.

---

## S3 — Model-written text is inserted into the page as HTML

**Where:**
* `templates/home/main_script.html` lines 539–541: `innerHTML = description_content…`,
  `innerHTML = chat_content`
* `templates/home/main_script_old_dolores.html` lines 450–452 (same code, older copy)
* `templates/demo/main_script.html` lines 70 and 93: `{{ persona_init_pos|safe }}`,
  `{{ all_movement|safe }}` inside a `<script>` block

**What it is:** each step, the page shows what every agent is doing and saying. That text is
**written by the language model**. The code puts it on the page with `innerHTML`, which tells the
browser "treat this as HTML". Anything in the text that looks like HTML tags will be interpreted as
page structure, not shown as letters.

The demo page does something similar on the server: it turns the whole movement history (again,
model-written) into JSON and marks it `|safe`, so Django doesn't escape it, then drops it inside a
`<script>` tag. If a model-written string happens to contain the sequence that closes a script tag,
the rest of that string is treated as HTML.

**Why it matters:** language models repeat what they read. Agents in this project remember and quote
each other, and in the "call -- load history" feature, memories come from a CSV file. Any HTML-like
text that gets into a memory can end up interpreted by your browser. At best that breaks the page
layout. At worst it runs script in the page, and that script can then use the unprotected endpoints
(S1, S2). This is an old, well-understood class of web bug; with AI-generated content it matters
*more*, because nobody reviews the text before it is displayed.

**When it bites:** whenever model output or imported history contains angle brackets. It doesn't need
an attacker; a model imitating HTML or Markdown can do it by accident.

**How to fix:**
1. Use `textContent` instead of `innerHTML` wherever the value is plain text (action, location).
2. For the chat panel, which uses `<br>` for line breaks, build the lines as elements:
   ```javascript
   const box = document.getElementById("chat__" + name);
   box.replaceChildren();
   for (const [speaker, line] of chats) {
     const div = document.createElement("div");
     div.textContent = speaker + ": " + line;
     box.appendChild(div);
   }
   ```
3. In the demo template, replace the `|safe` JSON with Django's
   [`json_script`](https://docs.djangoproject.com/en/stable/ref/templates/builtins/#json-script)
   filter, which escapes everything correctly:
   ```django
   {{ all_movement|json_script:"all-movement" }}
   <script>const all_movement = JSON.parse(document.getElementById("all-movement").textContent);</script>
   ```
   (The view must pass the Python dict, not a pre-dumped string.)

---

## S4 — The Django secret key is hard-coded and public

**Where:** `settings/base.py` line 23 and `settings/local.py` (same value), committed to a public repo.

**What it is:** Django uses `SECRET_KEY` to sign things it later trusts: session cookies, password
reset links, and signed values. Anyone who knows the key can forge those signatures. This key is on
GitHub, so everyone knows it.

**When it bites:** today the app has no user accounts and hardly uses sessions, so the practical risk
on a laptop is low. It becomes high if the admin site (S12) is ever used, if login is ever added, or
if the project is deployed with these settings. It is also a bad pattern for anyone who copies this
project as a starting point.

**How to fix:** read the key from the environment and refuse to start in production without one:

```python
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or "dev-only-" + "insecure"
if not DEBUG and SECRET_KEY.startswith("dev-only-"):
    raise RuntimeError("Set DJANGO_SECRET_KEY before running with DEBUG=False")
```

Because the old key has been public for years, **treat it as burned**: never reuse it anywhere.

---

## S5 — Debug mode is always on

**Where:** `settings/base.py` line 26, `settings/local.py`: `DEBUG = True`.

**What it is:** in debug mode, any crash shows a detailed error page with the code around the error,
local variable values, file paths, installed apps and settings. That is great while developing and
very bad for anyone else to see.

**Why it matters here:** this project crashes often on bad input (see the Coding review: missing files,
bad step numbers and unexpected model output all raise uncaught exceptions). Each crash would show a
visitor the server's internals. Debug mode also keeps a list of every database query in memory and
serves static files in a way Django documents as unsafe for production.

**How to fix:** `DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"`, and set
`ALLOWED_HOSTS = ["127.0.0.1", "localhost"]` explicitly, so that the server refuses requests addressed
to any other host name even if someone binds it to a public interface.

---

## S6 — Django 2.2 and many pinned packages are end-of-life

**Where:** `requirements.txt` (and its duplicate `environment/frontend_server/requirements.txt`).

**What it is:** the project pins exact old versions:

| Package | Pinned | Status |
|---|---|---|
| Django | 2.2 | End of support April 2022; no security fixes since. Current LTS line is 5.x |
| urllib3 | 1.26.7 | Older than several later security releases in the 1.26 line |
| requests | 2.26.0 | Several later security releases exist |
| Pillow | 8.4.0 | Many later security releases (image parsing bugs are common) |
| certifi | 2021.10.8 | Old list of trusted certificate authorities (some since removed for misconduct) |
| openai | 0.27.0 | Pre-1.0 client; the API calls it makes are for retired models (see the Coding review) |

**Why it matters:** "end-of-life" means that when a security hole is found, **no fix will be
released** for that version. Pinning old versions also means installing this project can *downgrade*
packages in a shared Python environment and weaken other projects on the same machine. This is one
reason the README recommends a virtualenv.

**When it bites:** mainly when the server is exposed, or when the environment is shared.

**How to fix:** upgrade Django to a supported LTS (the app uses very little of Django: plain views,
templates and static files, so this is a small job; the one removed API it uses is
`django.contrib.staticfiles.templatetags.staticfiles`, replaced by `{% load static %}`). Replace the
long pinned list with the handful of packages the code actually imports (see the Improvements
report). Use a lock file generated by a tool like `pip-tools` or `uv`, so updates are deliberate
and reviewable.

---

## S7 — Typed simulation names are used to copy and delete folders

**Where:** `reverie/backend_server/reverie.py`
* `__init__` line 58: `copyanything(fork_folder, sim_folder)` with both names from `input()`
* `open_server` lines 449 and 456: `shutil.rmtree(sim_folder)` for `exit` and `start path tester mode`

**What it is:** when you start the simulator, you type the name of the simulation to copy from and the
name of the new one. Both are used directly as folder names under `storage/`. Later, typing `exit`
**permanently deletes** the new simulation's folder, and so does `start path tester mode`.

**Why it matters:** this is mostly a **data-safety** problem rather than an attacker problem, but it
has the same root cause as S1: names from outside go into file paths unchecked.
* A typo is not caught. There is no check that the name is a simple folder name, so an unusual name
  can make "the new folder" resolve to somewhere other than a fresh folder under `storage/`. Then
  `exit` deletes whatever that path points to.
* `exit` deletes without asking. It's one word away from `fin`, the command that saves. There is no
  "are you sure?" and no backup.
* `start path tester mode` also deletes the simulation, which is surprising for a command whose name
  sounds like it only changes modes.

**How to fix:**
1. Validate both names with the same pattern as S1 (`^[A-Za-z0-9_-]{1,100}$`), and require that the
   new one does **not** already exist and the fork source **does**.
2. Before any `rmtree`, check that the resolved folder is directly inside `storage/` and that it
   contains `reverie/meta.json` (proof it is a simulation folder).
3. Ask for confirmation: `Type the simulation name to delete it without saving:`.
4. Move instead of delete: rename to `storage/.trash/<name>-<timestamp>` so mistakes are recoverable.

---

## S8 — The OpenAI key lives in a plain Python file that the code imports

**Where:** `reverie/backend_server/utils.py` (created by each user per the README; correctly listed
in `.gitignore`), imported with `from utils import *` in 7 modules, and set globally in
`gpt_structure.py` line 14 (`openai.api_key = openai_api_key`).

**What it is:** the README asks users to paste their OpenAI key into a Python source file. The file is
gitignored, which is good, but:
* **It's easy to leak anyway.** People zip up the folder to share results, copy `utils.py` into a
  pull request, paste it into an issue while debugging, or run `git add -f`. A key in a `.py` file
  also ends up in editor backups, cloud-synced folders and screenshots of the code.
* **`from utils import *` pulls the key into every module's namespace.** Any code that prints
  `globals()`, or a crash report that dumps local variables (see S5), can show it.
* **The key has no spending limit in the code.** A long simulation with many agents makes thousands
  of calls (my 25-minute, 3-agent test made about 600 completions plus 100 embeddings). Combined with
  the missing rate-limit handling (S9), a runaway loop can spend real money.

**How to fix:** read the key from the environment (the `openai` library already does this for
`OPENAI_API_KEY`), keep only non-secret paths in `utils.py`, and replace `import *` with explicit
imports. Document creating a **project key with a spending limit** in the OpenAI dashboard, and add
a simple call counter that stops a run after a configurable number of calls.

---

## S9 — Errors from the AI service are silently turned into "normal" text

**Where:** `persona/prompt_template/gpt_structure.py`: `ChatGPT_request` and `GPT4_request` catch
every exception and return the string `"ChatGPT ERROR"`; `GPT_request` returns `"TOKEN LIMIT
EXCEEDED"`.

**What it is:** when the call to the AI service fails (wrong key, no money left, network down, rate
limit, content filter), the code doesn't stop or retry properly. It returns an error message **as if
it were the model's answer**. That text then flows into the same validation, clean-up and memory
code as a real answer.

**Why it's a security concern and not just a bug:** it hides failures that users need to see.
* An **invalid or revoked key** looks the same as a model that answers badly.
* An **exhausted budget** doesn't stop the simulation; it keeps looping and hammering the API.
* **Rate limiting** is never backed off, which the README itself describes ("OpenAI's API can hang
  when it reaches the hourly rate limit").
* Error strings can be stored as agent memories and later shown in the UI or sent back to the model
  as context.

**How to fix:** let authentication and quota errors stop the run with a clear message; retry rate
limits and timeouts with increasing waits (e.g. 1 s, 2 s, 4 s, 8 s, then stop); never return an
error message where the model's text is expected (return `None` and handle it). See the Coding review
for a full replacement function.

---

## S10 — Third-party files are loaded from outside sites without integrity checks

**Where:**
* `templates/base.html` lines 23–24: Bootstrap from jsDelivr (with an integrity hash, good) and
  `https://code.jquery.com/jquery-latest.min.js` (**no** integrity hash, and "latest" is a moving name)
* `templates/home/main_script.html` 180–182 and `path_tester/main_script.html` 136–137: the character
  sprite sheet and its JSON from `mikewesthad.github.io`, a personal tutorial website
* `templates/base.html` (so **every page**): a visitor-map script from `clustrmaps.com`; and Phaser
  from jsDelivr on the map pages

**Why it matters:**
* **Anything loaded from another site runs with the full power of your page.** If that site is changed,
  hacked or taken over, its new content runs in your page. Pinned files with an `integrity="sha384-…"`
  attribute are safe from this; `jquery-latest` and the tutorial assets are not.
* **The tutorial website is a single point of failure.** During my test it wasn't reachable, and the
  replay and live simulator crashed (see the test report, G2). A personal blog's asset folder is not
  something to depend on.
* **The visitor-map script sends every page view to a third party.** That is a privacy issue (visitor
  IP addresses and pages) for anyone running a public demo, and it's never mentioned in the README.

**How to fix:** vendor (copy into `static_dirs/`) jQuery, Bootstrap and Phaser at pinned versions, or
keep the CDN with `integrity` and `crossorigin` attributes. Use the project's own character sprites
(`static_dirs/assets/characters/*.png` and `atlas.json`, already used by the demo page) instead of the
tutorial atlas. Remove the visitor-map script, or make it opt-in and say so.

---

## S11 — The settings loader falls back to a file that doesn't exist

**Where:** `frontend_server/settings/__init__.py`:

```python
from .base import *
try:
  from .local import *
  live = False
except:
  live = True
if live:
  from .production import *
```

**What it is:** if `local.py` is missing, or has any error at all (the bare `except:` catches
everything, including typos), the code tries to import `production.py`. That file isn't in the
repository, so the server crashes with a confusing `ModuleNotFoundError`. If someone *creates* a
`production.py` to fix that, a typo in `local.py` will silently switch a developer machine to
production settings, or the other way round.

**How to fix:** choose settings explicitly with `DJANGO_SETTINGS_MODULE`
(`frontend_server.settings.local` or `.production`), delete the try/except, and keep one
`base.py` with the shared values. `local.py` currently repeats all of `base.py` rather than
importing it; see the Code Quality review.

---

## S12 — Admin site and an unused database are enabled

**Where:** `frontend_server/urls.py` (`path('admin/', admin.site.urls)`), `INSTALLED_APPS`
(auth, sessions, admin), `db.sqlite3` checked into the repo **twice**
(`environment/frontend_server/db.sqlite3` and `…/frontend_server/db.sqlite3`),
`translator/models.py` with migrations.

**What it is:** the project doesn't use accounts or the admin site, but they're switched on, and the
database files are committed. Unused features are extra code paths that can have bugs, and committed
database files can contain whatever was in the author's local database (for example admin users with
password hashes). I didn't find credentials in them during this review, but the files shouldn't be
in the repository.

**How to fix:** remove `admin` and the auth/session apps unless you plan to use them, delete the
committed `db.sqlite3` files and add `*.sqlite3` to `.gitignore`. If the admin site is ever wanted,
it needs S4 (secret key) and S5 (debug) fixed first.

---

## What is already good

* `utils.py` is in `.gitignore`, so the most common way of leaking the key is blocked.
* URL patterns restrict `sim_code` to safe characters, which accidentally protects the replay and
  demo pages from path tricks.
* `runserver` defaults to listening only on `127.0.0.1`.
* The Bootstrap CDN links carry integrity hashes.
* The README warns that agents "lack human-like agency", and the terminal repeats it, which matters
  for responsible use of AI-driven characters.

## Recommended order of work

1. **Today, 30 minutes:** `ALLOWED_HOSTS`, `DEBUG` from the environment, `int(step)` plus the name check
   in the two JSON endpoints (S1, S5).
2. **This week:** CSRF back on (S2), `textContent` / `json_script` (S3), secret key from the
   environment (S4), confirm-before-delete (S7), key from the environment (S8).
3. **Next:** dependency upgrade to supported versions (S6), local static assets (S10), explicit
   settings modules (S11), trim unused apps (S12).
