# Generative Agents — Improvement Plan

**Date:** 30 September 2026 · **Revision:** `main` @ `36ea0d11`
**Question this report answers:** *If you want this project to run reliably today and be pleasant to
work on tomorrow, what should you do, in what order, and why that order?*

The other three reports list problems. This one turns them into a plan. Each step says **what to
do**, **why it matters**, **where in the code it happens**, **how to know you're done**, and
**roughly how long it takes** for one developer who knows Python. Numbers in brackets such as
[S1] or [C5] point to the matching finding in the Security Review (S) or Coding Review (C).

---

## How the plan is ordered

The order is driven by one idea: **make it run, then make it safe to change, then change it.**

1. **Phase 0 (one afternoon):** get the simulation running again on today's AI services. Nothing
   else matters if a fresh clone can't complete a single step.
2. **Phase 1 (about a week):** stop the silent failures and add a safety net of tests. After this
   phase, a mistake shows up as a red test instead of as an agent quietly "cooking in the bathroom".
3. **Phase 2 (two to three weeks):** the structural changes: one AI-calling layer, a proper link
   between browser and simulation, a lighter repository, faster memory search.
4. **Phase 3 (open-ended):** things that make the project better rather than just sound: cost
   controls, observability, new models, documentation for newcomers.

You can stop after any phase and have a strictly better project than before. The later phases
assume the earlier ones are done, mostly because the tests from Phase 1 are what let you do the
big refactors in Phase 2 without fear.

| Step | What | Phase | Effort | Fixes |
|---|---|---|---|---|
| 1 | Replace the retired model and the old OpenAI library | 0 | 2–4 h | C7, C19 |
| 2 | Five one-line crash fixes | 0 | 1 h | C1, C5, C6, C9, C10 |
| 3 | Lock down the local web server | 0 | 1–2 h | S1–S5, S11 |
| 4 | Turn silent failures into loud ones | 1 | 2–3 days | C2–C4, C8, S9 |
| 5 | Add an automated end-to-end test and CI | 1 | 2–3 days | Quality §testing |
| 6 | Clean the dependency list | 1 | half a day | S6, Quality §deps |
| 7 | Replace file polling with a direct connection | 2 | 3–5 days | C9, C11, C13, C18, Quality §IPC |
| 8 | Turn 36 prompt functions into data + one runner | 2 | 4–6 days | Quality §prompts |
| 9 | Move simulation output out of git; save safely | 2 | 1–2 days | C18, S12, Quality §storage |
| 10 | Fast memory search with NumPy | 2 | 1 day | C23, Quality §performance |
| 11 | Fix the map and the browser assets | 2 | 1 day | C15–C17, S10 |
| 12 | Delete the dead code | 2 | half a day | Quality §duplication |
| 13 | Cost and speed controls | 3 | 2–3 days | Quality §performance |
| 14 | Observability: see what an agent was thinking | 3 | 2–3 days | — |
| 15 | Documentation for the next person | 3 | 1–2 days | Quality §docs |

---

## Phase 0 — Make it run again

### Step 1. Replace the retired model and the old OpenAI library [C7, C19]

**What's wrong today.** Every "thinking" call in the simulation goes through
`reverie/backend_server/persona/prompt_template/gpt_structure.py`. That file uses
`openai==0.27` calling conventions (`openai.Completion.create`, `openai.ChatCompletion.create`,
`openai.Embedding.create`) and asks for `text-davinci-003`, a model OpenAI switched off in January 2024.
On a fresh clone with a valid key, the very first planning call fails. The failure is caught and turned
into the text `"TOKEN LIMIT EXCEEDED"` or `"ChatGPT ERROR"`, which the rest of the code then treats as
the model's answer [S9]. So the sim doesn't crash; it produces nonsense, or loops.

**What to do.**

1. Upgrade to the current `openai` library (1.x) and create one client object:
   `client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])`.
2. Write **one** function that every prompt goes through, for example
   `chat(prompt, *, max_tokens, temperature, stop=None) -> str`. Inside it: call
   `client.chat.completions.create(model=CHAT_MODEL, ...)`, retry on rate limits and timeouts with a
   growing wait (1 s, 2 s, 4 s, 8 s), and if it still fails, **raise an exception** called something
   like `LLMUnavailable`. Do not return a sentinel string. The Coding Review item C7 has a
   ready-to-paste version.
3. Point the three legacy entry points (`GPT_request`, `ChatGPT_request`, `GPT4_request`) at that new
   function so that the 36 functions in `run_gpt_prompt.py` keep working unchanged for now. Step 8
   replaces them properly.
4. Same for embeddings: one `embed(text) -> list[float]` using `text-embedding-3-small`. Note that the
   old model (`text-embedding-ada-002`) returns 1,536 numbers and `-3-small` also returns 1,536 by default,
   so existing saved memories stay compatible in shape. They are not *semantically* compatible,
   though: vectors from different models shouldn't be compared. Either re-embed old simulations once
   (a small script: read `embeddings.json`, call `embed` on each key, write back), or only use new
   simulations with the new model.
5. Put the model names in one place (`CHAT_MODEL`, `EMBED_MODEL`) read from environment variables with
   sensible defaults, so the next retirement is a one-line change.

**Why first.** Every other improvement needs a sim that can run for 20 steps so you can check it.

**Where.** `gpt_structure.py` (whole file), plus `utils.py` for the key (see step 3).

**Done when.** `python reverie.py`, fork `base_the_ville_isabella_maria_klaus`, `run 5` completes with
real, varied plans in the terminal and no "ERROR" strings in the saved `scratch.json`.

**Cost of running it.** In our hands-on testing, three agents over 150 steps made about 600 chat
calls and 100 embedding calls. With a small current model that's cents, not dollars. A default of a
small model is the right choice for a research toy; make the big model an opt-in.

---

### Step 2. Five one-line crash fixes [C1, C5, C6, C9, C10]

These are bugs that stop the program outright. Each is a line or two. Do them together in one
commit so they're easy to review.

* **Create the `movement/` folder before writing to it** (`reverie.py:400-401`). A freshly forked
  simulation doesn't have one, so the first step crashes with "No such file or directory". Add
  `os.makedirs(f"{sim_folder}/movement", exist_ok=True)` before the write. [C1]
* **`event.object.content` → `event.object`** (`associative_memory.py:298`). `object` is a plain
  string; asking a string for `.content` raises `AttributeError` the first time a memory with an
  object is summarised. [C5]
* **Fix the two tuple-in-f-string lines** (`associative_memory.py:284/290`). They build a string that
  literally contains `('Isabella', 'is', 'cooking')` instead of the words. It doesn't crash, but it
  feeds broken text into the prompts. [C6]
* **Guard the `os.remove(curr_step)` in the homepage view** (`views.py:120`). If the file is already
  gone (two tabs, a refresh), the page crashes with a 500. Wrap it in `try/except FileNotFoundError`
  or use `Path.unlink(missing_ok=True)`. [C9]
* **`rs.start_server` is referenced, never called** (`reverie.py:468`). Change to
  `rs.start_server(int(sim_command.split()[-1]))` or remove the branch. [C10]

**Done when.** A fresh fork runs `run 1` without touching the file system by hand.

---

### Step 3. Lock down the local web server [S1–S5, S11]

The Django app is meant to run on your own laptop. Even so, while it runs, any web page you open in the
same browser can talk to it, and the current settings make that easy. The fixes are small:

1. **Validate the simulation name and step number** in `process_environment` and
   `update_environment` (`views.py:241-295`). Accept only names matching `^[A-Za-z0-9_-]+$` and steps
   that are whole numbers; build paths through one helper that refuses anything that ends up outside
   the storage folder. The Security Review S1 shows the helper. This is the single most important
   security fix.
2. **Turn CSRF protection back on** (`settings/base.py:49`) and have the page send the token with its
   `fetch` calls (Django documents a three-line snippet that reads the `csrftoken` cookie). [S2]
3. **Stop writing model text into the page as HTML.** Use `textContent` instead of `innerHTML` in
   `home/main_script.html:539-541`, and `{{ data|json_script:"id" }}` instead of `|safe` in
   `demo/main_script.html:70,93`. [S3]
4. **Read `SECRET_KEY` from an environment variable**, generate a random one if it's missing in
   development, and **set `DEBUG` from an environment variable** defaulting to `False`, with
   `ALLOWED_HOSTS = ["127.0.0.1", "localhost"]`. [S4, S5]
5. **Fix the settings loader** (`settings/__init__.py`) so it doesn't try to import a
   `production.py` that isn't in the repo; just import `local`, or use `DJANGO_SETTINGS_MODULE`. [S11]
6. **Tell Django to listen only on your machine**: document `python manage.py runserver 127.0.0.1:8000`
   rather than `0.0.0.0`.

**Done when.** The request with a name like `../x` returns HTTP 400; a page on another site can't
POST to `/process_environment/` (403 from CSRF); model text containing `<b>` shows the literal
characters.

---

## Phase 1 — Make it safe to change

### Step 4. Turn silent failures into loud ones [C2–C4, C8, S9]

**The problem in plain words.** When something goes wrong in this codebase, the code usually
catches the error, prints nothing useful, and carries on with a made-up default. There are 98 bare
`except:` blocks. The most visible symptom is the "fail-safe" answers baked into the prompt
functions: if the model's answer about *where* to do something can't be parsed, the agent goes to
`"kitchen"` (`run_gpt_prompt.py:569, 699`). If it can't decide *how important* a memory is, it gets
a default score. The simulation keeps running and looks fine, but the agents' behaviour is quietly
being decided by fallbacks, and you have no way to know how often.

**What to do.**

1. **Count every fallback.** Add a small counter: `FALLBACKS[prompt_name] += 1` every time a
   fail-safe answer is used, and print a one-line summary at the end of each `run N`
   ("12 fallbacks this run: arena×8, poignancy×4"). This alone tells you whether the model and prompts
   are working. It's an hour of work and it's the most useful diagnostic in the plan.
2. **Validate "choose one of these" answers properly** [C3]. Many prompts ask the model to pick a
   location or object from a list. Today the answer is used as-is if it's not empty, even if it
   isn't one of the options, which then crashes later when the map lookup fails. Write one helper,
   `pick_option(answer, options)`, that normalises case and spaces, accepts an exact match, then a
   unique partial match, and otherwise returns `None` so the caller retries. The Coding Review has
   the code.
3. **Parse numbers with a regular expression** [C4]. `converse.py:267` does `int(answer)` on text
   like `"7. It's a big deal."`. Use `re.search(r"\d+", answer)` and clamp to the 1–10 range.
4. **Make `safe_generate_response` report failure honestly** [C8]: return `None` (or raise) instead
   of `False`, since `False` then flows into string code downstream.
5. **Replace bare `except:` with named exceptions**, starting with the ones in the main loop
   (`reverie.py`) and the prompt functions. Where you really do want to keep going, log the traceback
   with `logging.exception(...)` so it lands in a file. Don't try to fix all 98 at once; fix them as you
   touch each file in later steps.
6. **Use `logging` instead of `print`** for the 223 debug `print` calls, at `DEBUG` level. Default the
   console to `INFO` so a normal run shows progress, not a wall of prompt text, and write everything
   to `logs/<sim>.log`.

**Done when.** A run of 20 steps shows a fallback summary, and an unparseable answer produces a
retry and a log line, not an agent in the kitchen.

---

### Step 5. Add an automated end-to-end test and CI

**Why this is the most valuable step in the plan.** Right now the only way to know whether a change
broke something is to spend money on API calls and watch the browser for twenty minutes. With a
test that runs in under a minute for free, every later step becomes safe.

**The key trick: a stand-in model.** The test must not call a real AI. Since step 1 put every call
behind one `chat()` and one `embed()` function, the test can swap those out for a fake that:

* for `embed`, returns a deterministic vector derived from a hash of the text (so the same text
  always gets the same vector, and retrieval still works);
* for `chat`, looks at which prompt template is being filled and returns a valid, boring answer
  in the expected format: a schedule of hourly activities, an arena name from the options given in
  the prompt, a poignancy of `5`, and so on.

We built exactly this during hands-on testing (`docs/hands-on-test-2026-09-30/ga_standin.py`) and it
ran the real simulation for 150 steps with three agents, so this is proven, not theoretical.

**The test.**

1. Copy `base_the_ville_isabella_maria_klaus` into a temporary folder.
2. Start the simulation with the fake model, fork to `ci-test`.
3. Play the role of the browser: for each step, write `environment/N.json` with the agents'
   positions (the test can take them from the last movement file), then call the step function.
4. Run 20 steps, then `fin`.
5. Assert: 20 movement files exist; `reverie/meta.json` says `"step": 20`; each agent's
   `scratch.json` has a non-empty daily plan; `nodes.json` gained new memories; zero fallbacks.

**Smaller unit tests worth adding** (each a few lines):

* `pick_option` and the number parser from step 4.
* The path helper from step 3 rejects `..`, absolute paths and empty names.
* `new_retrieve` returns the most recent + relevant memory first on a tiny hand-made memory.
* `write_json_atomic` (step 9) leaves either the old file or the new file, never a half-written one.
* The Django views: `process_environment` with a bad name returns 400 (use Django's test client).

**CI.** A GitHub Actions workflow (`.github/workflows/test.yml`) that sets up Python 3.11, installs
the requirements, and runs `pytest`. There is no `.github` folder today. Keep it one job; it
should finish in under two minutes.

**Where to put it.** `tests/` at the repository root, with a `conftest.py` that adds
`reverie/backend_server` to the import path (the code uses flat imports like `from utils import *`).

**Done when.** A pull request that reintroduces the missing-`movement/` bug turns CI red.

---

### Step 6. Clean the dependency list [S6]

**What's wrong.** `requirements.txt` (two identical 68-line copies) pins 2023-era versions of
everything, including Django 2.2 (out of security support since April 2022), `openai==0.27`, and a
lot of packages the code never imports: `scikit-learn` is pinned but nothing imports it (cosine
similarity is done with NumPy), `selenium` is imported in `reverie.py:31` but never used, and
`django-storages` is imported only by `frontend_server/utils.py`, which nothing else imports. Old
pins mean old security holes, and a long list of unused packages means a slow, fragile install
(several of them fail to build on current Python).

**What to do.**

1. Delete the unused imports (`selenium` in `reverie.py`, the S3 helper in `frontend_server/utils.py`).
2. Write a new, short list with only what the code imports: `django` (4.2 LTS or 5.x), `openai`
   (1.x), `numpy`, and for tests `pytest`. That's it. Everything else in the old file is either a
   transitive dependency or unused.
3. Keep **one** requirements file at the root and delete the copies.
4. Generate a lock file (`pip-tools`' `pip-compile`, or `uv lock`) so installs are repeatable, and
   let Dependabot (a two-line config) open PRs when security updates appear.
5. Upgrading Django from 2.2 to 4.2 needs three small code changes in this project: `url()` →
   `path()`/`re_path()` in `urls.py`, `DEFAULT_AUTO_FIELD` in settings, and the template
   `{% load staticfiles %}` → `{% load static %}` (used in `landing.html`, `home.html` and `persona_state.html`, among others). Run the Django test from step 5 after.

**Done when.** `pip install -r requirements.txt` works on a clean Python 3.12 in under a minute.

---

## Phase 2 — Structural improvements

### Step 7. Replace file polling with a direct connection

**How it works today, in plain words.** The browser and the simulation never talk directly. Every
step, the browser saves the agents' positions as a file (`environment/N.json`) through a Django view;
the simulation checks the folder every fraction of a second for that file; when it appears, the
simulation thinks, then writes `movement/N.json`; meanwhile the browser asks Django every second
whether that file exists yet. Two programs, two folders and a lot of guessing about timing.

**Why it's a problem.**

* **It's fragile.** If either side restarts, a file is half-written, or two tabs are open, the step
  numbers get out of sync and the sim waits forever with no error [C9, C11, C13]. We hit this in
  testing.
* **It's slow.** Each step costs at least one polling interval on each side before any thinking
  happens.
* **It's hard to debug.** The only record of "what happened" is a pile of numbered files.
* **It's the root of several security findings**, because the web server has to accept file names
  from the browser [S1].

**What to do — two options, pick one.**

*Option A (smaller change): one process.* Run the simulation inside the Django process (or a small
FastAPI app) and expose two endpoints: `POST /sim/<name>/step` with the positions, returning the
movements directly in the response; and `GET /sim/<name>/state`. The browser's loop becomes "send
positions, wait for the answer, animate, repeat". No files, no polling, and the step number lives
in one place. Thinking takes seconds, so run the step in a worker thread and let the request wait,
or return a job id and have the browser poll that one id.

*Option B (keeps two processes): a socket.* Keep `reverie.py` as its own program but have it open
a local WebSocket (the `websockets` library is one import) on `127.0.0.1`. The browser connects
directly; messages are small JSON objects `{"step": 12, "positions": {...}}` and
`{"step": 12, "movements": {...}}`. Django goes back to only serving the page.

Either way:

* Keep **writing** the movement files after each step — they're a useful record and the replay
  and demo pages read them — but stop **using** files as the communication channel.
* Make the protocol carry the step number and reject a message for the wrong step with a clear
  error, instead of waiting.

**Why this is step 7 and not step 1.** It's the biggest change in the plan and touches both halves.
You want the end-to-end test from step 5 in place first: it plays the role of the browser, so you
change that test once to use the new channel and it tells you immediately whether the simulation
still behaves the same.

**Done when.** A 20-step run makes zero reads of the `environment/` folder, and opening a second
tab shows a clear "simulation already in use" message instead of freezing both.

---

### Step 8. Turn 36 prompt functions into data + one runner

**What's there today.** `run_gpt_prompt.py` is 2,930 lines. It has 36 functions, 32 of them named
`run_gpt_prompt_*`, and almost all have the same shape: build the input list, fill a `.txt`
template, call the model with a set of parameters, clean the answer with a local
`__func_clean_up`, check it with a local `__func_validate`, and use a hard-coded fail-safe if
it fails. The differences between functions are small (which template, which parameters, how to
clean the answer), but each is written out in full, so a fix to the retry logic has to be made 32
times, and in practice was made in some places but not others.

**What to do.** Describe each prompt as a small piece of data and write one function that runs any
of them:

```python
PromptSpec(
    name="action_arena",
    template="v1/action_location_object_vMar11.txt",
    inputs=lambda persona, sector, arenas: [...],     # what fills !<INPUT 0>! etc.
    parse=lambda text, ctx: pick_option(text, ctx["arenas"]),
    max_tokens=15, temperature=0, stop=["\n"],
    retries=3,
    fallback=None,                                    # None = raise, don't guess
)

answer = run_prompt(SPECS["action_arena"], persona=p, sector=s, arenas=options)
```

`run_prompt` handles filling the template, calling `chat()`, retrying, parsing, counting fallbacks
(step 4), logging the prompt and answer (step 14), and caching in tests. Each prompt definition
drops from ~80 lines to ~10.

**How to do it safely.** One prompt at a time. Convert it, run the end-to-end test, commit. Start
with the ones that caused real problems in testing (arena, object, poignancy, conversation), then
do the rest mechanically. Delete the old function once its spec is in place.

**Also:** the 109 `.txt` templates in `prompt_template/` include at least 59 that nothing reads.
Once every live prompt is a spec, the list of templates in use is just the list of specs; delete
the rest.

**Done when.** `run_gpt_prompt.py` is gone or under 500 lines, and changing the retry policy is a
one-line change.

---

### Step 9. Move simulation output out of git; save safely [C18, S12]

**What's there today.** The repository tracks **208,432 files, about 1.1 GB**. Almost all of it is
simulation output under `environment/frontend_server/storage/` and `compressed_storage/`, including
21 checkpoints of the same "July1" run. Every clone downloads all of it. Separately, the simulation
saves agent memory by writing JSON files directly, so if the program is killed mid-save (Ctrl+C,
out of memory, laptop sleeps) the file is left half-written and the simulation can't be loaded
again. Two SQLite database files are also committed.

**What to do.**

1. **Keep only the base simulations in git**: the three `base_*` folders you fork from. Move the
   July1 checkpoints and the compressed demos to a GitHub Release attachment or a small download
   script (`scripts/fetch_demo.sh`). Add `storage/*` with exceptions for `base_*` to `.gitignore`,
   plus `*.sqlite3`.
2. Existing clones will keep the history; that's fine. If the size of the history itself matters,
   rewriting history is a separate decision for the maintainers, not part of this plan.
3. **Save atomically.** Write every JSON save through one helper: write to `name.json.tmp`, flush,
   `os.replace` onto `name.json`. `os.replace` is a single step on every operating system, so the
   file is always either the old version or the new one [C18].
4. **Store embeddings as a NumPy file.** Isabella's `embeddings.json` is 7.4 MB for 912 memories,
   because each of the 1,536 numbers per memory is written out as text. As a `.npy` array plus a
   list of keys it's about 5.6 MB at full precision or 2.8 MB at half precision, and loads about 50×
   faster. Keep a loader for the old JSON format so existing sims still open.

**Done when.** A fresh clone is under 50 MB; killing the process during `fin` never leaves a
simulation that won't load.

---

### Step 10. Fast memory search with NumPy [C23]

**What's there today.** When an agent "remembers", `retrieve.py` loops over every memory in Python,
computes cosine similarity one pair at a time, normalises three score lists, and sorts
everything. It also asks the AI service to embed the question every time, even when the same
question was asked a moment ago (only `perceive.py:141-144` checks the cache; `retrieve.py:189`
does not). With 900 memories this is noticeable; after a long run with thousands, it dominates.

**What to do.**

1. Keep all embeddings in one NumPy matrix (rows = memories), which step 9 already stores.
2. Similarity for all memories at once: `sims = M @ q / (norms * np.linalg.norm(q))`.
3. Recency and importance as NumPy arrays too; combine with the same weights the code uses today
   (`gw = [0.5, 3, 2]` at `retrieve.py:244`, so behaviour doesn't change).
4. Pick the top N with `np.argpartition` instead of sorting everything.
5. Check the embedding cache before calling `embed()` in `retrieve.py`, same as `perceive.py` does.

**Check it didn't change behaviour.** Before the change, record which memories are retrieved for
50 queries on a saved simulation; after, compare. They should match except for ties.

**Done when.** Retrieval over 5,000 memories takes milliseconds and makes no network calls for a
repeated question.

---

### Step 11. Fix the map and the browser assets [C15–C17, S10]

* **Serve the character sprite sheet from the repo** instead of `mikewesthad`'s GitHub Pages site
  (C15). If that site goes away, every character disappears.
* **Four map textures are taller than 8,192 pixels** (512×10016 and similar) (C16). Many GPUs,
  and most phones, refuse textures that size, so parts of the map render black. Either cut them
  into two sheets each (a short Python/Pillow script), or start Phaser with `type: Phaser.CANVAS`
  as a quick fix.
* **Load scripts in the right order** in `base.html:23-24` so the page doesn't depend on timing (C17).
* **Pin the CDN scripts** (`jquery-latest` especially) to fixed versions with `integrity` hashes, or
  bundle them locally. **Remove the clustrmaps visitor tracker** from `base.html`: it loads on every
  page and sends every visitor's details to a third party, which a local research tool has no need
  for [S10].

**Done when.** The page loads with the network tab showing only `127.0.0.1` requests, and the full
map renders on a laptop with integrated graphics.

---

### Step 12. Delete the dead code

Straightforward, satisfying and makes every other step easier to read:

* `defunct_run_gpt_prompt.py` (2,179 lines, imported by nothing).
* Two of the three identical `global_methods.py` copies; import the one that remains.
* One of the two identical `requirements.txt` (step 6 already does this).
* `main_script_old_dolores.html` (no view renders it).
* The unused prompt templates (step 8 identifies them).
* `test.py` in the backend, which is a scratch script, not a test; move anything useful into `tests/`.
* `frontend_server/utils.py` (S3 storage helper, unused).
* Replace `check_if_file_exists` with `os.path.isfile` [C24].

Git keeps history, so nothing is lost. Run the end-to-end test after each deletion.

---

## Phase 3 — Make it better

### Step 13. Cost and speed controls

Running a simulation costs money and time in proportion to the number of AI calls. Today there's no
way to see or limit either.

* **Show a running total.** After each `run N`, print calls made, tokens used and an estimated
  cost. The `chat()` function from step 1 sees every call, so this is a counter and a price table.
* **A budget.** An optional `--max-cost 2.00` flag that stops cleanly (saving first) when reached.
* **Cache answers.** Many prompts repeat exactly (same agent, same time, same options). A small
  on-disk cache keyed by the hash of (model, prompt, parameters) avoids paying twice, and makes
  re-runs of the same sim reproducible. Turn it on by default for temperature-0 prompts.
* **Call in parallel.** Agents think independently within a step. Running their calls in a small
  thread pool (3–5 workers) cuts wall-clock time roughly by the number of agents, with no change to
  the result if you keep the order in which results are applied.
* **Batch embeddings.** The embeddings API accepts a list; embedding all new memories of a step in
  one call is cheaper and faster than one call each.

**Rough numbers to plan with** (from our 3-agent, 150-step test): ~600 chat calls and ~100
embeddings. At a small current model's prices that's well under a dollar; with a large model,
expect several dollars. Scale linearly with agents and steps. Cache hits during a re-run bring it
close to zero.

### Step 14. Observability: see what an agent was thinking

The most common question when watching the sim is "why did she do that?". Today the answer is buried
in `print` output. Improve it:

* Log every prompt/answer pair (step 8's runner makes this one line) to
  `storage/<sim>/trace/step-N.jsonl`, with agent, prompt name, answer, whether a fallback was used,
  and time taken.
* Add a panel to the existing browser page: click an agent, see their last few prompts and answers
  from the trace. This turns the most confusing part of the project into its most interesting.
* A `replay-trace` command that re-runs a step using the recorded answers, so a bug seen once can
  be reproduced without calling the AI.

### Step 15. Documentation for the next person

The README explains the research well but a newcomer still hits every problem we hit. Add:

* **A "first run in 10 minutes" guide** that matches the code after steps 1–6: install, set
  `OPENAI_API_KEY`, start both parts (or one, after step 7), fork the base sim, `run 10`, open the
  browser. Include the expected output so people know it's working.
* **"How a step works"**: one page with a diagram of perceive → retrieve → plan → reflect →
  execute, naming the file for each, and where memories are stored.
* **"Adding or changing a prompt"**: how a `PromptSpec` works (step 8), how to test it with the
  stand-in model.
* **A cost note** from step 13.
* **A troubleshooting table**: "sim frozen at step N" → check the step numbers, "agent always in
  the kitchen" → check the fallback summary, etc.

---

## What not to do

A few tempting changes that aren't worth it, at least not before the plan above:

* **Don't rewrite from scratch.** The ideas and structure are sound; the problems are all
  fixable in place, one step at a time, with the test from step 5 as a safety net.
* **Don't swap the game engine.** Phaser works; the rendering problems are texture sizes (step 11),
  not the engine.
* **Don't add a database for memories** yet. The JSON/NumPy files are fine at this scale; step 9
  makes them safe. A database becomes interesting only if you run dozens of agents for weeks.
* **Don't chase every bare `except:` in one go.** Fix them as you touch the code; a big-bang
  change to 98 error handlers without tests is how you introduce new bugs.

---

## Summary

Three steps (an afternoon) get the project running on today's AI services and close the obvious
security holes. Three more (a week) give it a test suite and make failures visible. The Phase 2
steps (a few weeks) make the codebase smaller, faster and much easier to work on. None of it needs
a rewrite, and each step leaves the project better than it was even if you stop there.
