"""Scripted OpenAI-compatible stand-in for Generative Agents (openai==0.27 client).

NOT an AI. Returns deterministic, template-shaped answers so the simulation machinery
(fork, step loop, frontend sync, save, replay, compress, demo) can be exercised without a
model. Every request is logged to ga_standin.log with the prompt-template it came from.
"""
import hashlib, json, math, re, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open(sys.argv[1] if len(sys.argv) > 1 else "ga_standin.log", "a", buffering=1)
COUNTS = {}


def embed(text):
    # deterministic pseudo-embedding (1536 dims, unit length) — similar strings share words -> share buckets
    v = [0.0] * 1536
    for w in re.findall(r"[a-z]+", text.lower()) or ["empty"]:
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % 1536] += 1.0
        v[(h >> 11) % 1536] += 0.5
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def kind_of(prompt):
    p = prompt
    rules = [
        ("safety", r"Rate the concern"),
        ("wake_up_hour", r"wakes up at|wake up hour|In general, .*\n.*wakes up"),
        ("daily_plan", r"Today is .*Here is .*plan today in broad-strokes|in broad-strokes"),
        ("hourly_schedule", r"Hourly schedule|hourly schedule format"),
        ("task_decomp", r"Describe subtasks in 5 min increments|in 5 min increments"),
        ("action_arena", r"MUST pick one of \{"),
        ("action_sector", r"Area options"),
        ("action_object", r"Which one of the following objects|Pick ONE most relevant object"),
        ("pronunciatio", r"emoji"),
        ("event_triple", r"\(subject, predicate, object\)|Task: Turn the input into"),
        ("poignancy", r"On the scale of 1 to 10"),
        ("decide_to_talk", r"Should .* initiate a conversation|would .* initiate"),
        ("decide_react", r"Option 1:|Option 2:"),
        ("focal_points", r"salient high-level questions|high-level questions"),
        ("insights", r"high-level insights|infer from the above statements"),
        ("summarize_chat", r"Summarize the conversation"),
        ("convo", r"conversation|Conversation|utterance"),
        ("new_schedule", r"revised schedule|Revise"),
    ]
    for k, rx in rules:
        if re.search(rx, p):
            return k
    return "other"


def answer(prompt, chat=False):
    k = kind_of(prompt)
    COUNTS[k] = COUNTS.get(k, 0) + 1
    tail = prompt[-900:]
    names = re.findall(r"([A-Z][a-z]+ [A-Z][a-z]+)", tail)
    name = max(set(names), key=names.count) if names else "The agent"
    if k == "wake_up_hour":
        out = "7"
    elif k == "daily_plan":
        out = ("1) wake up and complete the morning routine at 7:00 am, 2) have breakfast at 8:00 am, "
               "3) work on the day's main task from 9:00 am to 12:00 pm, 4) have lunch at 12:00 pm, "
               "5) continue working from 1:00 pm to 5:00 pm, 6) have dinner at 6:00 pm, 7) relax and go to bed at 11:00 pm")
    elif k == "hourly_schedule":
        out = "working on the day's main task"
    elif k == "task_decomp":
        out = ("1) " + name + " is gathering what they need. (duration in minutes: 15, minutes left: 45)\n"
               "2) " + name + " is focusing on the task. (duration in minutes: 30, minutes left: 15)\n"
               "3) " + name + " is wrapping up. (duration in minutes: 15, minutes left: 0)")
    elif k == "action_arena":
        m = re.findall(r"MUST pick one of \{([^{}]+)\}", prompt)
        out = m[-1].split(",")[0].strip() + "}"
    elif k == "action_sector":
        m = re.findall(r"Area options: \{([^{}]+)\}", prompt) or re.findall(r"\{([^{}]+)\}", prompt)
        opts = [o.strip() for o in m[-1].split(",")] if m else []
        own = [o for o in opts if name in o]
        out = (own[0] if own else (opts[0] if opts else "main room")) + "}"
    elif k == "action_object":
        # echo the first quoted/braced option offered in the prompt so validators accept it
        opts = re.findall(r"\{([^{}]+)\}", prompt)
        cand = [o.split(",")[0].strip() for o in opts if o.strip()]
        out = cand[-1] if cand else "main room"
    elif k == "pronunciatio":
        out = "🙂"
    elif k == "event_triple":
        out = "(" + name + ", is, busy)"
    elif k == "poignancy":
        out = "3"
    elif k == "decide_to_talk":
        out = "no"
    elif k == "decide_react":
        out = "Option 3"
    elif k == "focal_points":
        out = "1) What is " + name + " working on?\n2) Who does " + name + " spend time with?\n3) What matters to " + name + "?"
    elif k == "insights":
        out = "1. " + name + " values a steady routine (because of 1, 2)"
    elif k == "safety":
        out = "1"
    elif k == "summarize_chat":
        out = "a short friendly chat"
    else:
        out = "okay"
    LOG.write(json.dumps({"t": time.time(), "kind": k, "chat": chat, "prompt_tail": prompt[-400:], "out": out}) + "\n")
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        path = self.path
        if path.endswith("/embeddings"):
            inp = body.get("input", [""])
            inp = inp if isinstance(inp, list) else [inp]
            COUNTS["embedding"] = COUNTS.get("embedding", 0) + 1
            return self._send({"object": "list", "data": [{"object": "embedding", "index": i, "embedding": embed(t)} for i, t in enumerate(inp)],
                               "model": body.get("model"), "usage": {"prompt_tokens": 1, "total_tokens": 1}})
        if path.endswith("/chat/completions"):
            prompt = "\n".join(m.get("content", "") for m in body.get("messages", []))
            out = answer(prompt, chat=True)
            if re.search(r'"output"', prompt):  # ChatGPT_safe_generate_response expects {"output": ...}
                out = json.dumps({"output": out})
            return self._send({"id": "x", "object": "chat.completion", "model": body.get("model"),
                               "choices": [{"index": 0, "message": {"role": "assistant", "content": out}, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        if path.endswith("/completions"):
            out = answer(body.get("prompt", ""))
            return self._send({"id": "x", "object": "text_completion", "model": body.get("model"),
                               "choices": [{"index": 0, "text": out, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
        self.send_response(404); self.end_headers()

    def do_GET(self):
        if self.path.endswith("/stats"):
            return self._send(COUNTS)
        self.send_response(404); self.end_headers()


ThreadingHTTPServer(("127.0.0.1", 7788), H).serve_forever()
