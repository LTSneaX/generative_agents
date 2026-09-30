# Generative Agents — Code Quality Review

**Date:** 30 September 2026 · **Revision:** `main` @ `36ea0d11`
**Question this report answers:** *How easy is this codebase to understand, run, change and trust?*
It looks at the project as a whole: structure, duplication, error handling, testing, data layout,
performance, documentation and tooling. Line-by-line bugs are in the **Coding Review**; risks to
people and data are in the **Security Review**; the step-by-step plan is in **Improvements**.

---

## 1. The short version

Generative Agents is an influential research codebase. The **ideas are clearly expressed**: the
folder names mirror the paper (perceive, retrieve, plan, reflect, execute, converse), the
functions have real docstrings, and a reader who knows the paper can find their way. That is rarer
than it should be in research code.

What holds it back is that it is still shaped like **a research prototype frozen at the moment the
paper was submitted**:

* No automated tests and no continuous integration, so nothing tells you when something breaks.
* Errors are swallowed almost everywhere (98 bare `except:` blocks), so when something does break,
  it breaks quietly and far away from the cause.
* A large amount of dead and duplicated code: a 2,179-line "defunct" file, three identical copies of
  a helper module, an unused old template, and at least 59 of 109 prompt files that nothing reads.
* The two halves of the app talk by **writing JSON files and polling for them**, which is slow,
  fragile and hard to debug.
* The repository carries **208,432 tracked files (about 1.1 GB on disk)** of simulation output,
  mostly 21 checkpoints of the same run.
* The AI-calling layer is built around services and a library version that no longer work.

Scores (1 = poor, 5 = excellent), with the reasoning in the sections below:

| Area | Score | One-line reason |
|---|---|---|
| Readability of core logic | 4 | Paper-aligned structure, docstrings, clear names in the cognitive modules |
| Structure & modularity | 2 | Import-star everywhere, global state, huge prompt file, file-based messaging |
| Duplication & dead code | 1 | Three copies of helpers, a whole "defunct" module, unused templates and prompts |
| Error handling | 1 | 98 bare `except:`; failures turn into fake data |
| Testing & CI | 1 | No tests, no CI; `test.py` is a scratch script |
| Data & storage design | 2 | Human-readable JSON is great for research, but it is huge, not crash-safe, and committed |
| Performance & scalability | 2 | Linear memory scans, JSON embeddings, fixed sleeps, one call at a time |
| Dependencies & setup | 1 | 68 pinned packages (most unused), Python 3.9-only pins, retired APIs |
| Documentation | 3 | Good README for the happy path; setup gaps and no architecture notes |

---

## 2. Structure and modularity

### 2.1 What the structure gets right

```
reverie/backend_server/
  reverie.py                  the simulation loop and the terminal commands
  maze.py, path_finder.py     the tile map and walking
  persona/
    persona.py                one agent; calls the modules below in order
    cognitive_modules/        perceive, retrieve, plan, reflect, execute, converse
    memory_structures/        associative (long-term), spatial (places), scratch (short-term)
    prompt_template/          everything that talks to the language model
environment/frontend_server/  Django app: map rendering, replay, demo
```

This maps one-to-one onto the paper's architecture diagram. `persona.py` reads like the paper's
agent loop (`perceive → retrieve → plan → reflect → execute`). For a research audience that's
exactly right, and any refactor should **keep these names and this shape**.

### 2.2 `from X import *` everywhere

Seven backend modules start with `from utils import *`, and most also `from global_methods import *`,
`from persona.prompt_template.run_gpt_prompt import *` and so on. The effect:

* **You can't tell where a name comes from.** Reading `plan.py`, a call to `ChatGPT_safe_generate_response`
  or `fs_storage` could come from any of five imports.
* **Name clashes win silently.** If two star-imported modules define the same name, the later
  import quietly replaces the earlier one.
* **Secrets spread.** `utils.py` holds the OpenAI key (Security S8), and `import *` copies it into
  every module that imports it.
* **Tools can't help you.** Editors and linters can't reliably find usages or unused imports.

**Better:** explicit imports (`from utils import fs_storage, maze_assets_loc`) and a small `config.py`
that reads from environment variables.

### 2.3 Global state and hidden coupling

* `reverie.py` line 468, inside the `ReverieServer` class, calls **`rs.start_server(...)`**, which is
  the global variable created at the bottom of the file, instead of `self.start_server(...)`. It works
  only because the script creates exactly one server named `rs`. Import the class from anywhere else
  (a notebook, a test) and `run` fails with `NameError`.
* The OpenAI client is configured by setting a module-level global (`openai.api_key = …`) at import time.
* The current simulation name and step are passed between processes through
  `temp_storage/curr_sim_code.json` and `curr_step.json`, which are also **tracked by git**, so simply
  using the app changes committed files.

### 2.4 The front end and back end talk through files

The two servers never talk directly:

1. The backend writes `storage/<sim>/movement/<step>.json`.
2. The browser asks Django every few frames "does step N exist yet?" (`/update_environment/`).
3. Django checks the disk and sends it back.
4. The browser sends the new world state to Django (`/process_environment/`), which writes
   `environment/<step>.json`.
5. The backend polls the disk every 0.1 s (`time.sleep(self.server_sleep)`) until that file appears.

**Why this is a quality problem:**
* **It's slow by design.** Every step waits on at least one polling interval on each side.
* **It's fragile.** If the browser tab is in the background (browsers throttle timers), closed, or
  crashes, the backend waits forever with no message. I hit this during testing: a background tab
  froze the loop.
* **It's hard to debug.** There is no single place that shows the conversation between the two
  sides; you have to watch files appear.
* **Partial files are possible.** Nothing guarantees a reader doesn't open a file while the writer is
  halfway through it. The bare `except:` around the read (`reverie.py` 318–325) hides the resulting
  JSON errors, which is probably why it's there.
* **Replay has to reuse the same polling machinery**, so replay also breaks when the page stalls.

The design made sense for a paper prototype where the author always had both windows open. For
anyone else, a single process (or a small web API between the two) would be simpler and much more
robust. See Improvements, step 7.

### 2.5 One enormous prompt module

`persona/prompt_template/run_gpt_prompt.py` is **2,930 lines** with 36 functions, 32 of them named
`run_gpt_prompt_*`. Each one repeats the same recipe:

1. build a list of strings for the template,
2. choose a template file from `v1/`, `v2/` or `v3_ChatGPT/`,
3. define an inner `__func_validate` and `__func_clean_up`,
4. define a `get_fail_safe()`,
5. call one of the generate helpers,
6. often a second, older path left in comments.

This copy-paste structure is why the same class of bug appears many times (for example, fail-safe
values that aren't valid for the current map; see the Coding Review C3). A fix in one place
doesn't reach the others. **Better:** one small "prompt spec" per prompt (template, inputs, parser,
validator, fallback) and one generic runner. The Improvements report shows the shape.

---

## 3. Duplication and dead code

| What | Where | Evidence |
|---|---|---|
| A whole old prompt module | `persona/prompt_template/defunct_run_gpt_prompt.py` | 2,179 lines, 33 functions, **imported by nothing** |
| The same helper module, three times | `reverie/global_methods.py`, `reverie/backend_server/global_methods.py`, `environment/frontend_server/global_methods.py` | byte-for-byte identical (`diff` shows no differences) |
| The same requirements, twice | `requirements.txt`, `environment/frontend_server/requirements.txt` | identical 68-line files |
| An old copy of the main page script | `templates/home/main_script_old_dolores.html` | not referenced by any view or template |
| Unused prompt templates | `prompt_template/v1`, `v2`, `v3_ChatGPT` | 109 `.txt` files; **at least 59 are not referenced** by any live code |
| Two settings files that repeat each other | `settings/base.py`, `settings/local.py` | `local.py` re-declares the whole of `base.py` instead of importing it |
| Two committed databases | `environment/frontend_server/db.sqlite3`, `…/frontend_server/db.sqlite3` | neither is used by the app |
| Commented-out code | e.g. `views.py` 253–255 and 281–283, `reverie.py` 602–606, `gpt_structure.py` alternative paths | old code kept "just in case" |

**Why it matters:** every copy is a place where a fix gets applied to one version and not the others.
Dead code isn't free: new contributors read it, search results land in it, and it makes the living
code look bigger and scarier than it is. Git already remembers old versions, so deleting is safe.

---

## 4. Error handling

There are **98 bare `except:` blocks** across the Python code. A bare `except:` catches *everything*:
typos, missing files, wrong types, Ctrl-C, and bugs in the code itself. It then usually does
`pass`, `print("Error.")`, or returns a made-up value.

Three patterns matter most:

1. **Failures turn into fake data.** `ChatGPT_request` returns the string `"ChatGPT ERROR"`,
   `GPT_request` returns `"TOKEN LIMIT EXCEEDED"`, and the `*_safe_generate_response` helpers return
   a "fail-safe" value when validation fails. The simulation carries on as if the model had said
   that. In my test, a non-answer turned into a stored "conversation" made of `"..."` lines. For a
   research tool, **silently fabricated behaviour is the worst kind of failure**, because it can end
   up in results.
2. **Whole commands are wrapped in one try/except.** `open_server` wraps every terminal command in a
   single `try: … except: traceback.print_exc(); print("Error.")`. That's why a crash on step 1 of
   `run 30` shows "Error." and drops you back at the prompt with the simulation in an unknown,
   half-updated state.
3. **Hiding real bugs.** `check_if_file_exists` uses `try: open() except: return False`, so
   "permission denied" and "file does not exist" look the same.

**Better:**
* Catch only what you expect (`FileNotFoundError`, `json.JSONDecodeError`, the OpenAI library's rate
  limit error).
* When the model's answer can't be used, **record that it failed** (a counter, a log line, a flag
  on the memory) instead of inventing a plausible answer, and make "strict mode" (stop on failure)
  available for research runs.
* When a step fails, don't leave half-applied state; either roll back to the last saved checkpoint
  or stop the run.

---

## 5. Testing and continuous integration

* **No test suite.** `reverie/backend_server/test.py` is a 76-line scratch script that calls the
  OpenAI API with a hard-coded prompt. It isn't a test and needs a paid key to run.
* **No CI.** There is no `.github/workflows` folder, so nothing checks a change before it's merged.
  Several of the bugs I found in testing (the missing `movement/` folder, the `"kitchen"` fallback,
  the `print … (chat)` crash) would have been caught by the most basic "fork, run 10 steps, save" test.
* **Hard to test as written**, because model calls happen deep inside every module through global
  functions. There's no seam where a test could plug in a fake model.

The good news: **it's easy to add a very valuable test.** During this review I wrote a 150-line fake
OpenAI server (`docs/hands-on-test-2026-09-30/ga_standin.py`) that returns well-formed answers. With it:

1. start the fake server,
2. fork `base_the_ville_isabella_maria_klaus`,
3. run 20 steps with a fake frontend (write `environment/<n>.json` files the way the browser does),
4. assert that 20 movement files exist, `fin` saves, and `meta.json` says step 20.

That single end-to-end test runs in seconds, costs nothing, and protects the whole pipeline.
The Improvements report lays out this test and a handful of unit tests.

---

## 6. Data and storage

### 6.1 What's good

Everything an agent knows is saved as **plain, readable JSON**: `scratch.json` (current plan),
`spatial_memory.json` (places it knows), `nodes.json` (memories), `kw_strength.json` and
`embeddings.json`. For research this is a real strength: you can open an agent's mind in a text
editor, diff two runs, and share a simulation as a folder.

### 6.2 What's not

| Problem | Evidence | Why it matters |
|---|---|---|
| Embeddings stored as JSON text | Isabella's `embeddings.json` is **7.4 MB for 912 memories**, about 8 KB each | Each memory's 1,536 numbers are written as text with full decimals. A binary format (NumPy `.npy`) would be about a quarter of the size and much faster to load |
| Output committed to git | **208,432 tracked files**, 1.1 GB on disk; 21 checkpoints of the July1 run, each with thousands of per-step movement files | Slow clones, huge checkouts, and every run by a user shows up as untracked noise. Most of this belongs in a release download |
| One file per step | 8,655 movement files for one simulated day | File systems and git handle hundreds of thousands of tiny files badly. `compress_sim_storage.py` already shows the fix: one `master_movement.json` |
| Saves aren't crash-safe | `associative_memory.save`, `scratch.save`, `spatial_memory.save` open the real file with `"w"` and write | If the process dies mid-write (Ctrl-C, out of memory, laptop sleeps), the file is left half-written and the simulation can't be loaded again. Write to a temporary file and rename it over the old one, which is atomic on all major systems |
| No format version | `meta.json` has no schema version | When the data layout changes, old simulations fail with confusing KeyErrors instead of a clear "this simulation needs migrating" |
| Missing folders | Base simulations have no `movement/` folder because git doesn't store empty folders | Every fresh clone crashes on the first `run` (test report G3) |

---

## 7. Performance and scalability

Nothing here matters for a 3-agent demo. All of it matters for the 25-agent town in the paper, and
more for anything bigger.

* **Memory retrieval scans every memory, every time.** `retrieve.py → new_retrieve` rebuilds and
  sorts the full list of an agent's memories for **each focal point**, then computes recency,
  importance and similarity for **all** of them in Python loops (`extract_relevance` calls `cos_sim`
  once per memory). Cost grows with memory count times number of questions, and memory only grows.
  With NumPy, one matrix multiplication replaces thousands of Python-level calls; with a small
  vector index it becomes near-constant time.
* **Every model call is sequential.** Agents are processed one after another, and each makes several
  blocking calls. Agents that don't interact in a step could be processed in parallel.
* **Fixed sleeps.** `temp_sleep()` waits 0.1 s before some calls, and the main loop polls every
  0.1 s. Small individually, but paid thousands of times per simulated day.
* **Embeddings are only cached in one place.** `perceive.py` (lines 141–144) checks
  `persona.a_mem.embeddings` before calling the API, which is good. But `retrieve.py` line 189
  requests a fresh embedding for **every focal point on every retrieval**, even when the same
  question was embedded a moment ago, and reflection, planning and conversation always request new
  ones. A small shared cache (text → vector) in `get_embedding` itself would cover every path.
* **Measured cost:** my 3-agent, 150-step (25-minute) run made **~600 completion calls and ~100
  embedding calls**. Extrapolating linearly, one simulated day for 25 agents is on the order of
  hundreds of thousands of calls. The README's warning that runs are "somewhat costly" understates
  it; users deserve a rough cost estimate before they start.

---

## 8. Dependencies and setup

* **68 pinned packages, most unused.** The code actually imports: Django, django-cors-headers,
  django-storages (listed in `INSTALLED_APPS` but never used), numpy, openai, and the standard
  library. scikit-learn is pinned but **never imported**; cosine similarity is done with NumPy. Pins like `selenium`, `trio`, `seaborn`, `statsmodels`,
  `yellowbrick`, `gensim`, `boto`, `trueskill` and `psycopg2-binary` aren't needed to run the project.
* **Python 3.9 only in practice.** Pins such as `numpy==1.25.2`, `Pillow==8.4.0` and `gensim==3.8.0`
  have no wheels for current Python versions, so `pip install -r requirements.txt` fails on 3.11+.
  In testing I installed only the ~8 packages actually used.
* **Retired external APIs.** `text-davinci-003` (legacy completions) was shut down by OpenAI in
  January 2024, and `openai==0.27`'s calling style was replaced in v1.0. As shipped, the simulation
  can't run against OpenAI at all.
* **Manual steps that could be automatic:** creating `utils.py`, creating the `movement/` folder,
  editing `compress_sim_storage.py` to change the simulation name.

---

## 9. Style and readability details

* **Two-space indentation and `print (x)` with a space.** Unusual for Python (PEP 8 uses four
  spaces). Not wrong, but auto-formatters like `black` or `ruff format` would normalise it in one
  commit and remove the question forever.
* **Mixed naming:** `ChatGPT_safe_generate_response`, `GPT4_request`, `run_gpt_prompt_act_obj_desc`,
  `new_retrieve` (the old `retrieve` also still exists), `get_str_accessible_sector_arenas`.
* **223 `print` calls** used as the only logging. There's no way to turn verbosity up or down, and
  prompts and responses are printed to the terminal mixed with the command prompt.
* **Docstrings are genuinely good** in the cognitive modules and memory structures: they explain
  inputs, outputs and intent. Keep that habit.
* **Magic values:** tile collision block id `"32125"`, `server_sleep = 0.1`, retrieval weights
  (`[0.5, 3, 2]` in `new_retrieve`), `n_count=30`, and prompt retry counts (`repeat=3`, `repeat=5`)
  are scattered constants. They are tuning knobs that researchers will want to change, so they
  belong in one config file with comments on what each does.

---

## 10. Documentation

**Good:** the README walks through setup, running, replay, demo and customisation clearly, with
examples, and credits the artists.

**Missing:**
* An **architecture page**: which process does what, how the two servers talk, and what each file
  in `storage/<sim>/` contains. I had to read code to learn that `environment/N.json` is written by
  the browser and `movement/N.json` by the backend.
* The **full list of terminal commands** (`print persona schedule`, `call -- analysis`,
  `call -- load history`, …); the README shows only three.
* **Cost and time expectations** per agent-hour.
* **Supported Python versions** and a minimal install list.
* **Known limitations:** needs a visible browser tab; one browser tab only; background tabs stall
  the loop.

---

## 11. Bottom line

The research core is sound and readable. The quality problems are almost all **around** it: missing
tests, swallowed errors, file-based plumbing, duplicated and dead code, stale dependencies, and a
repository full of data. None of them need a rewrite. The Improvements report orders the fixes so that
each step is small, testable, and leaves the paper's architecture exactly as it is.
