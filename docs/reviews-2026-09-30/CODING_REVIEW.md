# Generative Agents — Coding Review

**Date:** 30 September 2026 · **Revision:** `main` @ `36ea0d11`
**What this report is:** a line-level review of the code. It lists the specific places where the
code does the wrong thing, or will do the wrong thing in a situation that's easy to reach, and
shows how to fix each one. Every item names the file and line, explains *what happens* in plain
words, says *when* a user will run into it, and gives a concrete fix.

Items marked **Seen in testing** were reproduced during the hands-on run
(`docs/hands-on-test-2026-09-30/REPORT.md`). The rest were found by reading the code; the reasoning
is spelled out so it can be checked.

---

## Index

| # | Bug | Where | Seen in testing |
|---|---|---|---|
| C1 | First `run` crashes on a fresh clone: `movement/` folder missing | `reverie.py:400-401` | yes |
| C2 | The room fallback `"kitchen"` crashes the run it's supposed to rescue | `run_gpt_prompt.py:569, 699`; `spatial_memory.py:107` | yes |
| C3 | The model's room/object choice is used without checking it exists | `plan.py:221`, `spatial_memory.py:107` | yes |
| C4 | Interview mode crashes on any non-numeric safety score | `converse.py:267` | yes |
| C5 | `print persona associative memory (chat)` always crashes | `associative_memory.py:298` | yes |
| C6 | Event and thought listings print Python tuples instead of text | `associative_memory.py:284, 290` | by reading |
| C7 | API failures become fake model answers | `gpt_structure.py:31-47, 73-80, 197-224` | yes |
| C8 | `*_safe_generate_response` returns `False` or ignores its fallback | `gpt_structure.py:84-190` | by reading |
| C9 | Opening the simulator page twice breaks it | `views.py:109-120` | yes |
| C10 | `run` calls a global variable instead of `self` | `reverie.py:468` | by reading |
| C11 | Persona State ignores the step you opened it from | `views.py:186-232` | yes |
| C12 | Persona State assumes memory ids have no gaps | `views.py:209-211` | by reading |
| C13 | Demo crashes with a server error for a step past the end | `views.py:72-74` | by reading |
| C14 | Demo start time computed with a loop | `views.py:43-44` | by reading |
| C15 | Replay/simulator depend on a tutorial website's sprite sheet | `home/main_script.html:180-182` | yes |
| C16 | Interiors don't render on GPUs with an 8,192-pixel texture limit | map assets + `main_script.html` | yes |
| C17 | Bootstrap's script loads before jQuery | `base.html:23-24` | yes |
| C18 | Saving can corrupt a simulation if interrupted | `associative_memory.py:140-150`, `scratch.py:309`, `spatial_memory.py:39` | by reading |
| C19 | Retired OpenAI model and client | `gpt_structure.py`, `run_gpt_prompt.py` | yes |
| C20 | Unknown terminal commands are silently ignored | `reverie.py` `open_server` | yes |
| C21 | `exit` deletes without confirmation | `reverie.py:452-456` | yes |
| C22 | Hard-coded simulation name in the compress script | `compress_sim_storage.py:62-63` | yes |
| C23 | Memory retrieval scans everything, every time | `retrieve.py:199-270` | by reading |
| C24 | `check_if_file_exists` can't tell "missing" from "not allowed" | `global_methods.py:160-170` | by reading |

---

## C1 — First `run` crashes on a fresh clone: `movement/` folder missing

**Where:** `reverie/backend_server/reverie.py` lines 400–401

```python
curr_move_file = f"{sim_folder}/movement/{self.step}.json"
with open(curr_move_file, "w") as outfile:
```

**What happens:** `open(…, "w")` creates the file but not missing folders. The two base simulations
in the repository (`base_the_ville_isabella_maria_klaus`, `base_the_ville_n25`) have no `movement/`
folder, because **git doesn't store empty folders**. When you fork a base simulation, the copy has
no `movement/` either, and the first step fails with
`FileNotFoundError: …/movement/0.json`.

**When:** the very first `run` for every new user who follows the README. It worked for the author
because their local copy had the folder.

**Fix (one line):**

```python
os.makedirs(f"{sim_folder}/movement", exist_ok=True)   # in __init__, after copyanything
```

Also add an empty `storage/base_*/movement/.gitkeep` so the folder exists in fresh clones.

---

## C2 — The room fallback `"kitchen"` crashes the run it is supposed to rescue

**Where:** `persona/prompt_template/run_gpt_prompt.py` lines 569 and 699:

```python
def get_fail_safe():
    fs = ("kitchen")
    return fs
```

and `persona/memory_structures/spatial_memory.py` line 107:

```python
x = ", ".join(list(self.tree[curr_world][curr_sector][curr_arena.lower()]))
```

**What happens:** when the model's answer to "which room should Isabella go to?" can't be parsed,
the code uses the fail-safe `"kitchen"`. But rooms are **per building**. Isabella's apartment only
has `main room`. The next line looks up `tree[world][sector]["kitchen"]`, which doesn't exist, and
raises `KeyError: 'kitchen'`. The whole `run` command aborts ("Error." at the prompt), leaving the
simulation in whatever state it was in mid-step.

**When:** any time the model gives an unusable answer for a building without a kitchen. It happened
on my first run. Real models produce unusable answers regularly (extra words, quotes, a room name
from a different building).

**Fix:** make the fallback depend on what's actually available:

```python
def get_fail_safe():
    options = persona.s_mem.get_str_accessible_sector_arenas(act_sector)   # e.g. "main room, bathroom"
    return options.split(",")[0].strip() if options else "main room"
```

(The function already has `persona` and the sector in scope; `get_fail_safe` just needs to close over
them.) Apply the same idea to the sector fallback and the object fallback.

---

## C3 — The model's room/object choice is used without checking it exists

**Where:** `persona/cognitive_modules/plan.py` lines ~200–225 (`generate_action_sector`,
`generate_action_arena`, `generate_action_game_object`) and every `spatial_memory` lookup that uses
the result.

**What happens:** C2 is one symptom of a general problem. The validators in `run_gpt_prompt.py` only
check the **shape** of the answer ("not empty", "contains `}`", "no comma"). They never check that
the room or object is **one of the options that were offered**. A perfectly plausible answer like
`"Living Room"` (capitalised, or from another building) passes validation and then crashes the
lookup, or makes the agent walk to the wrong place.

**When:** routinely with real models. It's the most likely cause of the mid-run "Error." that the
README's tips section attributes to API hangs.

**Fix:** validate against the offered list, and fall back to a *valid* option:

```python
def pick_option(answer, options):
    """Return the option that matches the model's answer, or None."""
    a = answer.strip().strip('"\'{} .').lower()
    for opt in options:
        if a == opt.lower():
            return opt
    for opt in options:                      # tolerate "the main room", "main room please"
        if opt.lower() in a:
            return opt
    return None
```

Use it in the three `generate_action_*` functions: if it returns `None`, retry once, then use the
first option and **log** that a fallback was used (see C7).

---

## C4 — Interview mode crashes on any non-numeric safety score

**Where:** `persona/cognitive_modules/converse.py` line 267

```python
if int(run_gpt_generate_safety_score(persona, line)[0]) >= 8:
```

**What happens:** every line you type in `call -- analysis <name>` is first scored for "is the user
treating the agent like a person" on a 1–10 scale. The code converts the model's answer straight to
a number. If the model says `"8/10"`, `"eight"`, `"Score: 3"` or anything that isn't a bare integer,
`int()` raises `ValueError` and the whole interview ends with "Error.".

**When:** the first time a model adds any words to its number. Seen in testing.

**Fix:**

```python
import re
def parse_score(text, default=1):
    m = re.search(r"\b(10|[1-9])\b", str(text))
    return int(m.group(1)) if m else default

score = parse_score(run_gpt_generate_safety_score(persona, line)[0])
if score >= 8:
    ...
```

The same unguarded `int(...)` pattern appears in other score parsers (e.g. poignancy). Search for
`int(gpt_response` and use `parse_score` everywhere.

---

## C5 — `print persona associative memory (chat)` always crashes

**Where:** `persona/memory_structures/associative_memory.py` line 298

```python
ret_str += f"with {event.object.content} ({event.description})\n"
```

**What happens:** for chat memories, `event.object` is stored as a **plain string** (the other
person's name), not an object with a `.content` attribute. So the line always raises
`AttributeError: 'str' object has no attribute 'content'`.

**When:** every time you run this terminal command on an agent who has had a conversation.
Seen in testing.

**Fix:** `ret_str += f"with {event.object} ({event.description})\n"`.

---

## C6 — Event and thought listings print Python tuples instead of text

**Where:** `associative_memory.py` lines 284 and 290

```python
ret_str += f'{"Event", len(self.seq_event) - count, ": ", event.spo_summary(), " -- ", event.description}\n'
```

**What happens:** everything inside one pair of `{ }` is evaluated as a **single Python expression**.
Here that expression is a tuple of six values, so the output looks like
`('Event', 912, ': ', ('Isabella Rodriguez', 'is', 'sleeping'), ' -- ', 'Isabella Rodriguez is sleeping')`
instead of `Event 912: … -- …`.

**When:** every use of `print persona associative memory (event)` and `(thought)`. It works, just
unreadably.

**Fix:** one pair of braces per value:

```python
ret_str += f"Event {len(self.seq_event) - count}: {event.spo_summary()} -- {event.description}\n"
```

---

## C7 — API failures become fake model answers

**Where:** `persona/prompt_template/gpt_structure.py`
* `ChatGPT_request` (≈ lines 59–81) and `GPT4_request` (≈ 33–56): `except: return "ChatGPT ERROR"`
* `GPT_request` (≈ 197–224): `except: return "TOKEN LIMIT EXCEEDED"`

**What happens:** any failure (wrong key, network error, rate limit, timeout, content filter, a
typo in the code) is caught, and a *string* is returned where the model's answer is expected. That
string then goes through validation. Usually validation rejects it, the retry loop tries again
(immediately, with no pause), and finally the "fail-safe" answer is used. The simulation keeps
running with invented behaviour, and nothing records that it wasn't the model's choice.

**When:** whenever the API has trouble, which the README says happens ("OpenAI's API can hang when it
reaches the hourly rate limit"). Also every time the key is wrong: the whole simulation runs on
fallback answers and looks almost normal.

**Fix:** one wrapper that retries the right errors with growing waits, fails loudly on the others,
and never returns a fake answer:

```python
import time, random, logging
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError, AuthenticationError

log = logging.getLogger("llm")
client = OpenAI()                       # reads OPENAI_API_KEY from the environment

class LLMUnavailable(RuntimeError): pass

def chat(prompt, model="gpt-4o-mini", max_tries=5):
    delay = 1.0
    for attempt in range(1, max_tries + 1):
        try:
            r = client.chat.completions.create(model=model,
                                               messages=[{"role": "user", "content": prompt}])
            return r.choices[0].message.content
        except AuthenticationError as e:
            raise LLMUnavailable("OpenAI rejected the API key") from e      # never retry
        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            log.warning("LLM call failed (%s), retry %d in %.1fs", type(e).__name__, attempt, delay)
            time.sleep(delay + random.random() * 0.3)
            delay *= 2
    raise LLMUnavailable(f"gave up after {max_tries} attempts")
```

The simulation loop should catch `LLMUnavailable`, **save**, and stop with a clear message, rather
than continue on fallback answers.

---

## C8 — `*_safe_generate_response` returns `False` or ignores its fallback

**Where:** `gpt_structure.py`
* `GPT4_safe_generate_response` (≈ 84–120) and `ChatGPT_safe_generate_response` (≈ 123–164) take a
  `fail_safe_response` argument but **return `False`** when all tries fail (lines 120 and 164).
* `ChatGPT_safe_generate_response_OLD` and `safe_generate_response` return `fail_safe_response`
  (lines 190, 273).

**What happens:** callers expect a string (a room name, a list of subtasks), but may get `False`.
Some callers then call `.split()` or `.strip()` on it and crash with `AttributeError: 'bool' object
has no attribute 'split'`, far away from the real cause. Others test `if output:` and treat the
failure as "no answer", which isn't the same as the fail-safe their author intended.

**Fix:** decide one contract and apply it everywhere. The clearest is: return the validated
answer, or raise a specific exception (`ModelAnswerUnusable`) that callers either handle or let
stop the step. If fallbacks are wanted, return
`(answer, used_fallback: bool)` so the caller can log it.

---

## C9 — Opening the simulator page twice breaks it

**Where:** `environment/frontend_server/translator/views.py` lines 109–120

```python
if not check_if_file_exists(f_curr_step):
    return render(request, "home/error_start_backend.html", {})
...
os.remove(f_curr_step)
```

**What happens:** the backend writes `temp_storage/curr_step.json` when it starts. The page reads it,
then **deletes it**. Refreshing the page, opening a second tab, or the browser reloading on its own
all hit the "Please start the backend first" page, even though the backend is running.

**When:** any refresh of `/simulator_home` during a run. Easy to hit, and confusing, because the
message says the opposite of the truth.

**Fix:** don't delete the file in the view. The backend already knows the current step; have it
overwrite `curr_step.json` whenever the step advances (or expose it through a small endpoint) and let
the page read it as often as it likes.

---

## C10 — `run` calls a global variable instead of `self`

**Where:** `reverie.py` line 468, inside `ReverieServer.open_server`:

```python
rs.start_server(int_count)
```

**What happens:** `rs` is the variable created at the very bottom of the file
(`rs = ReverieServer(origin, target)`). Inside the class it only works by luck. Create the server any
other way (`server = ReverieServer(...)` in a notebook, a test, or another script), and typing
`run 10` raises `NameError: name 'rs' is not defined`.

**Fix:** `self.start_server(int_count)`.

---

## C11 — Persona State ignores the step you opened it from

**Where:** `views.py` `replay_persona_state` lines 186–232. The `step` argument is converted to
`int` (line 188) and then **never used**; the view always loads `…/bootstrap_memory/`, which is the
state at the **end** of the simulation.

**What happens:** during a replay at 3:33 pm, clicking "State Details" shows the agent's memories
and plan as of midnight at the end of the run. The page shows the wrong "Current time", memories
from events that haven't happened yet in the replay, and a schedule that may have been replaced.

**Why it's not a one-line fix:** the saved simulation only keeps memory at the end; there's no
per-step memory snapshot to load.

**Fix options:**
1. **Honest labelling (easy):** show "State at end of simulation (step N)" at the top of the page,
   and hide the misleading "Current time" field.
2. **Filter by time (medium):** memories have a `created` timestamp. Filter `nodes.json` to
   memories created before the replay's current time. That gives the correct memory list; plan
   and scratch still reflect the end state and should be labelled as such.
3. **Snapshots (larger):** save `scratch.json` every N steps during a run.

---

## C12 — Persona State assumes memory ids have no gaps

**Where:** `views.py` lines 209–211

```python
for count in range(len(associative.keys()), 0, -1):
    node_id = f"node_{str(count)}"
    node_details = associative[node_id]
```

**What happens:** it assumes memory ids are exactly `node_1 … node_N`. If one memory is ever removed
(or a future version starts ids at 0, or skips one), `associative[node_id]` raises `KeyError`, and
the page shows a server error, with a full debug page because DEBUG is on (Security S5).

**Fix:** iterate over what's actually there, sorted:

```python
def node_num(k): return int(k.split("_")[1])
for node_id in sorted(associative, key=node_num, reverse=True):
    node_details = associative[node_id]
```

---

## C13 — Demo crashes with a server error for a step past the end

**Where:** `views.py` lines 72–74: `val = raw_all_movement[key]` for every step up to the requested
one.

**What happens:** `/demo/<sim>/99999/3/` raises `KeyError` and returns a 500 error page. The same
happens for a `sim_code` that doesn't exist (`FileNotFoundError` at line 37).

**Fix:** check the step against `len(raw_all_movement)`, use `os.path.exists` for the files, and
return a friendly 404 with the valid range (`"This simulation has 8,655 steps"`).

---

## C14 — Demo start time is computed with a loop

**Where:** `views.py` lines 43–44

```python
for i in range(step):
    start_datetime += datetime.timedelta(seconds=sec_per_step)
```

**What happens:** it adds 10 seconds, `step` times. For step 8,000 that's 8,000 loop iterations
where one multiplication is enough. Not slow enough to notice today, but it's the kind of thing
that becomes a problem in bigger runs.

**Fix:** `start_datetime += datetime.timedelta(seconds=sec_per_step * step)`.

---

## C15 — Replay and simulator depend on a tutorial website's sprite sheet

**Where:** `templates/home/main_script.html` lines 180–182 (also `path_tester/main_script.html`
136–137 and `main_script_old_dolores.html` 128–129):

```javascript
this.load.atlas("atlas",
  "https://mikewesthad.github.io/phaser-3-tilemap-blog-posts/post-1/assets/atlas/atlas.png",
  "https://mikewesthad.github.io/phaser-3-tilemap-blog-posts/post-1/assets/atlas/atlas.json");
```

**What happens:** the walking-character animations come from a Phaser tutorial's website. When
that site can't be reached (offline, a school firewall, a corporate proxy, or it's taken down), the
animations `misa-left-walk` etc. don't exist. The first call to `anims.play(...)` throws
`Cannot read properties of undefined (reading 'duration')`, the game loop stops, and the replay
freezes on step 1 with no visible error. Seen in testing.

**Fix:** the demo page already loads the project's own sprites
(`templates/demo/main_script.html` 158–164):

```javascript
this.load.atlas("atlas", "{% static 'assets/characters/Yuriko_Yamamoto.png' %}",
                          "{% static 'assets/characters/atlas.json' %}");
```

The local `atlas.json` names its frames `down-walk.000`, `left`, … instead of `misa-front-walk.000`,
`misa-left`, … So either copy the demo's per-persona loading into `home/main_script.html` and rename
the animation keys (`misa-front-walk` → `down-walk`, `misa-back-walk` → `up-walk`), or ship a local
copy of the tutorial atlas (check its licence first). The first is better: each agent then gets its
own sprite in replay too, which fixes the "all characters look identical" limitation the README
describes.

---

## C16 — Interiors don't render on GPUs with an 8,192-pixel texture limit

**Where:** tileset images in `static_dirs/assets/the_ville/visuals/map_assets/v1/`:

| file | width × height |
|---|---|
| `interiors_pt1.png` | 512 × 10,016 |
| `interiors_pt2.png` | 512 × 10,016 |
| `interiors_pt3.png` | 512 × 10,032 |
| `interiors_pt5.png` | 512 × 9,024 |

and the Phaser config (`type: Phaser.AUTO`, which picks WebGL when available).

**What happens:** WebGL can only upload textures up to the GPU's maximum size. Many integrated
laptop GPUs, most phones, virtual machines and software renderers allow at most **8,192** pixels per
side. These four images are taller, so the upload fails (`WebGL: INVALID_VALUE: texImage2D: width or
height out of range`), and every tile from them is drawn as black: all furniture and interior floors.
Separately, 10,032 isn't a multiple of 32 (the tile size), which Phaser warns about.

**Fix options:**
1. **Simplest:** use the Canvas renderer (`type: Phaser.CANVAS` in the game config). I verified this
   makes every interior render in the same browser. Canvas is slower for very large maps but fine
   for this one.
2. **Best:** re-slice each tall image into two images of at most 8,192 px (e.g. 512 × 5,008 each) and
   register them as separate tilesets in Tiled; then WebGL works everywhere. Also crop
   `interiors_pt3.png` to a multiple of 32.

---

## C17 — Bootstrap's script loads before jQuery

**Where:** `templates/base.html` lines 23–24

```html
<script src="https://cdn.jsdelivr.net/npm/bootstrap@3.4.1/dist/js/bootstrap.min.js" …></script>
<script src="https://code.jquery.com/jquery-latest.min.js" type="text/javascript"></script>
```

**What happens:** Bootstrap 3's JavaScript requires jQuery to already exist. Loaded first, it throws
"Bootstrap's JavaScript requires jQuery" on every page and none of its components work. The pages
barely use Bootstrap's JavaScript, which is why this went unnoticed, but it's an error on every page
load that hides real errors in the console.

**Fix:** swap the two lines and pin jQuery to a specific version with an integrity hash
(`jquery-latest` has been frozen at 1.11.1 since 2014).

---

## C18 — Saving can corrupt a simulation if interrupted

**Where:** `associative_memory.save` (lines 140–150), `scratch.save` (309), `spatial_memory.save` (39),
and `ReverieServer.save`. All open the real file with `"w"` and write into it.

**What happens:** opening with `"w"` empties the file immediately. If the process stops before the
write finishes (Ctrl-C, out of memory, laptop sleep, disk full), the file is left empty or cut off.
The next load fails with a JSON error, and the agent's memory for that simulation is lost. Embedding
files are several megabytes (7.4 MB for Isabella in the July1 run), so the window isn't tiny.

**Fix:** write to a temporary file in the same folder, then rename it over the old one. The rename
is atomic on Windows, macOS and Linux, so there's always either the complete old file or the
complete new one:

```python
import json, os, tempfile
def write_json_atomic(path, data, **kw):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, **kw)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp); raise
```

---

## C19 — Retired OpenAI model and client

**Where:** `gpt_structure.py` (`openai.Completion.create(model=gpt_parameter["engine"] …)`,
`openai.ChatCompletion.create`, `openai.Embedding.create`) and the many
`gpt_param = {"engine": "text-davinci-003", …}` dictionaries in `run_gpt_prompt.py`.

**What happens:**
* `text-davinci-003` and the legacy Completions endpoint for it were shut down by OpenAI in January
  2024. Every prompt that uses it now fails, and through C7 turns into fallback answers.
* `openai==0.27` uses the pre-1.0 calling style (`openai.ChatCompletion.create`), which current
  versions of the library don't support.
* `gpt-3.5-turbo` and `text-embedding-ada-002` still work at the time of writing, but newer, cheaper
  models are recommended.

**Fix:** move all calls to the 1.x client through **one** function (see the C7 wrapper), route the
old completion-style prompts to a chat model (wrap the prompt as a single user message; the prompt
templates are already plain text), and make the model names configuration rather than code.
Because model choice changes results, record the model name in each simulation's `meta.json` so
runs stay comparable.

---

## C20 — Unknown terminal commands are silently ignored

**Where:** `reverie.py` `open_server`: the long `if/elif` chain has no final `else`.

**What happens:** a typo like `rn 10` or `print persona schedul Isabella Rodriguez` does nothing and
shows a new prompt. Users can't tell whether the command ran.

**Fix:** add
`else: print(f"Unknown command: {sim_command!r}. Type 'help' for the list.")` and add a `help`
command that prints every supported command (the list is currently only in the source).

---

## C21 — `exit` deletes without confirmation

**Where:** `reverie.py` lines 452–456 (`exit`) and 445–450 (`start path tester mode`), both calling
`shutil.rmtree(sim_folder)`.

**What happens:** `exit` permanently deletes the simulation you have been running, with no
question, even after hours of paid API calls. `fin` (save) and `exit` (delete) are both short words
at the same prompt.

**Fix:** ask first (`Discard all progress in 'my-sim'? Type the name to confirm:`), and move the
folder to `storage/.trash/` instead of deleting. The Security review (S7) covers the path checks
to add at the same time.

---

## C22 — Hard-coded simulation name in the compress script

**Where:** `reverie/compress_sim_storage.py` lines 62–63

```python
if __name__ == '__main__':
  compress("July1_the_ville_isabella_maria_klaus-step-3-9")
```

**What happens:** to compress your own run you have to edit the script. The README says so, but it's
an easy thing to do wrong, and it's also the kind of edit that ends up committed by accident.

**Fix:**

```python
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Compress a simulation for the demo page")
    p.add_argument("sim_code")
    compress(p.parse_args().sim_code)
```

---

## C23 — Memory retrieval scans everything, every time

**Where:** `persona/cognitive_modules/retrieve.py` `new_retrieve` (≈ 199–270) and its helpers
`extract_recency`, `extract_importance`, `extract_relevance`.

**What happens:** for **each focal point** (the questions an agent asks its memory, usually several
per step), the code:
1. builds a list of **all** event and thought memories,
2. sorts it by last-access time,
3. computes recency, importance and similarity for **every** memory in Python loops (similarity calls
   `cos_sim` with two 1,536-number lists, one memory at a time),
4. normalises and combines the scores,
5. sorts again to take the top 30.

It's correct, but the cost grows with the number of memories times the number of questions, and
agents never forget, so each simulated day is slower than the last.

**Fix (same results, far less work):** keep the embeddings in one NumPy matrix alongside the memory
list, updated when a memory is added. Similarity for all memories is then one line:

```python
sims = M @ q / (np.linalg.norm(M, axis=1) * np.linalg.norm(q))   # M: n×1536, q: 1536
```

Recency and importance can be vectors too. Use `np.argpartition` to take the top 30 without sorting
everything. This keeps the paper's scoring formula exactly while turning thousands of Python-level
operations into a few array operations.

---

## C24 — `check_if_file_exists` can't tell "missing" from "not allowed"

**Where:** `global_methods.py` lines 160–170 (in all three copies)

```python
try:
    with open(curr_file) as f_analysis_file: pass
    return True
except:
    return False
```

**What happens:** any error, including "permission denied", "is a directory", or a bad path,
reports "doesn't exist". Callers then take the wrong branch. For example, the simulator page shows
"Please start the backend first" when the real problem is file permissions.

**Fix:** `return os.path.isfile(curr_file)`. Where the caller then opens the file, just open it and
catch `FileNotFoundError` specifically.

---

## Patterns behind these bugs

Most of the 24 items come from four habits. Fixing the habit prevents the next dozen bugs:

1. **Trusting the model's answer.** The model is a source of *untrusted text*. Validate against
   what was offered (C2, C3), parse numbers defensively (C4), and never let a parse failure crash
   the loop.
2. **Hiding failure.** Returning fake answers or `False`, and catching everything (C7, C8, C24),
   turns every bug into a mystery. Fail loudly, log fallbacks, stop cleanly.
3. **Assuming the author's machine.** Folders that exist locally (C1), a website that's online
   (C15), a GPU with big textures (C16), a browser tab in the foreground. A clean-clone test in CI
   would catch these.
4. **Copy-paste instead of a shared helper.** The same bug appears in many prompt functions and
   three copies of `global_methods.py`. One helper, one fix.
