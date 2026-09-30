# Generative Agents — Review Pack (30 September 2026)

Four reports on this repository at `main` @ `36ea0d11`, written after running the project
end-to-end (see `docs/hands-on-test-2026-09-30/`) and then reading the code line by line.
Each report stands on its own; they cross-reference each other by finding number.

| Report | Question it answers | Findings |
|---|---|---|
| [SECURITY.md](SECURITY.md) | What could harm the people running it, or their data and keys? | S1–S12 |
| [CODE_QUALITY.md](CODE_QUALITY.md) | How easy is it to understand, run, change and trust? | Scored areas |
| [CODING_REVIEW.md](CODING_REVIEW.md) | Which specific lines are wrong, and what's the fix? | C1–C24 |
| [IMPROVEMENTS.md](IMPROVEMENTS.md) | What to do, in what order, and how long it takes | Steps 1–15 |

## If you only read one page

* **It doesn't run as-is today.** It calls `text-davinci-003`, which OpenAI retired in January
  2024, through a library version (`openai==0.27`) whose API has since changed. Failures are turned
  into fake answers instead of errors, so the sim appears to run but produces nonsense.
  → Improvements step 1, Coding Review C7/C19.
* **A freshly forked simulation crashes on step 1** because the `movement/` folder isn't created.
  → Coding Review C1 (one line).
* **The local web server trusts file names sent by the browser** and has CSRF protection switched
  off, so any web page open in the same browser can make it write files.
  → Security S1, S2.
* **There are no tests and no CI**, and errors are swallowed in 98 places, so breakages are silent.
  → Code Quality, Improvements steps 4–5.
* **The repository is 1.1 GB / 208,432 files**, mostly copies of old simulation output.
  → Improvements step 9.

The first three phases of the plan are about **four weeks of one person's time** and require no
rewrite.

## How these were produced

* Everything was checked against the code at the revision above; file and line references are to
  that revision.
* Runtime claims (crashes, freezes, counts of AI calls) come from actually running the simulation
  in a cloud container with a stand-in model; see the hands-on test report for the logs.
* Security findings describe the risk, where it is and how to fix it. They deliberately do not
  include attack instructions.
