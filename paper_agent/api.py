from __future__ import annotations

import argparse
import datetime as dt
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from paper_agent.agent import load_config, run_agent


DEFAULT_CONFIG_PATH = Path("paper_agent/config.toml")
TOPIC_HISTORY_PATH = Path("paper_agent/topic_history.json")
CONFIG_KEYS = [
    "topics",
    "max_results",
    "report_dir",
    "report_name_prefix",
    "llm_enabled",
    "llm_model",
    "llm_api_key_env",
    "llm_max_output_tokens",
    "html_enabled",
    "auto_open_html",
    "fetch_multiplier",
    "max_fetch_cap",
    "min_relevance_score",
    "recent_days",
    "arxiv_timeout_seconds",
    "arxiv_max_retries",
    "arxiv_backoff_base_seconds",
    "arxiv_user_agent",
]

WEB_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Paper Agent Dashboard</title>
  <style>
    :root {
      --bg: #f3f5f7;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #4b5563;
      --accent: #0f766e;
      --border: #d1d5db;
    }
    body {
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #eefdf8 0%, var(--bg) 50%);
      color: var(--ink);
    }
    .wrap {
      max-width: 1800px;
      margin: 0 auto;
      padding: 20px 14px 40px;
    }
    .grid {
      display: grid;
      gap: 14px;
      grid-template-columns: 300px minmax(0, 1fr);
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 14px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04);
    }
    .panel.report-panel {
      padding: 0;
      border: none;
      box-shadow: none;
      background: transparent;
      border-radius: 0;
    }
    label {
      display: block;
      margin: 8px 0 6px;
      font-size: 13px;
      color: var(--muted);
    }
    .section-title {
      margin: 12px 0 4px;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: #6b7280;
      font-weight: 700;
    }
    .helper {
      margin-top: 6px;
      font-size: 12px;
      color: #6b7280;
    }
    .history-list {
      margin-top: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 170px;
      overflow: auto;
      padding-right: 2px;
    }
    .history-item {
      border: 1px solid #d1d5db;
      border-radius: 8px;
      background: #f8fafc;
      color: #0f172a;
      padding: 7px 8px;
      font-size: 12px;
      cursor: pointer;
      text-align: left;
      line-height: 1.35;
    }
    .history-item:hover {
      background: #eef2ff;
      border-color: #c7d2fe;
    }
    .history-meta {
      display: block;
      margin-top: 2px;
      color: #64748b;
      font-size: 11px;
    }
    input, textarea, select, button {
      width: 100%;
      box-sizing: border-box;
      border-radius: 8px;
      border: 1px solid #cbd5e1;
      padding: 9px 10px;
      font-size: 14px;
      font-family: inherit;
    }
    textarea {
      min-height: 84px;
      resize: vertical;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    button {
      background: var(--accent);
      color: white;
      font-weight: 600;
      cursor: pointer;
      border: none;
      margin-top: 12px;
    }
    button:disabled {
      opacity: 0.65;
      cursor: wait;
    }
    .status {
      margin-top: 10px;
      font-size: 13px;
      color: var(--muted);
      white-space: pre-wrap;
    }
    iframe {
      width: 100%;
      min-height: 88vh;
      border: none;
      border-radius: 0;
      background: transparent;
    }
    @media (max-width: 900px) {
      .grid { grid-template-columns: 1fr; }
      iframe { min-height: 60vh; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Paper Agent Dashboard</h1>
    <div class="grid">
      <section class="panel">
        <div class="section-title">Topic</div>
        <label for="topics">Topics (one per line)</label>
        <textarea id="topics"></textarea>
        <div class="helper">Recent Topics</div>
        <div id="topic_history" class="history-list"></div>

        <div class="section-title">Output</div>
        <div class="row">
          <div>
            <label for="min_relevance_score">Min relevance score</label>
            <input id="min_relevance_score" type="number" min="0" step="0.1" value="7.0" />
          </div>
          <div>
            <label for="top_k">Top K in report</label>
            <input id="top_k" type="number" min="1" value="10" />
          </div>
        </div>

        <div class="section-title">Time Window</div>
        <div class="row">
          <div>
            <label for="recent_window">Published within</label>
            <select id="recent_window">
              <option value="3">Last 3 days</option>
              <option value="7" selected>Last 1 week</option>
              <option value="30">Last 1 month</option>
              <option value="custom">Custom days</option>
            </select>
          </div>
          <div>
            <label for="recent_days_custom">Custom days</label>
            <input id="recent_days_custom" type="number" min="1" value="14" />
          </div>
        </div>

        <div class="section-title">Retrieval</div>
        <div class="row">
          <div>
            <label for="max_results">Base fetch size</label>
            <input id="max_results" type="number" min="1" value="30" />
          </div>
          <div>
            <label for="fetch_multiplier">Fetch multiplier</label>
            <input id="fetch_multiplier" type="number" min="1" value="3" />
          </div>
        </div>
        <div class="helper">
          Actual fetch count = min(Base fetch size × Fetch multiplier, max_fetch_cap)
        </div>

        <button id="run">Save + Retrieve Papers</button>
        <div class="status" id="status">Loading current config...</div>
      </section>

      <section class="panel report-panel">
        <iframe id="report" src="/report/latest"></iframe>
      </section>
    </div>
  </div>

  <script>
    const statusEl = document.getElementById("status");
    const runBtn = document.getElementById("run");
    const reportFrame = document.getElementById("report");
    const topicHistoryEl = document.getElementById("topic_history");

    function setStatus(msg) { statusEl.textContent = msg; }

    function renderTopicHistory(rows) {
      if (!rows || !rows.length) {
        topicHistoryEl.innerHTML = '<div class="helper">No history yet.</div>';
        return;
      }
      topicHistoryEl.innerHTML = rows.map((row, idx) => {
        const topics = (row.topics || []).join(' | ');
        const count = row.count ?? 1;
        const ts = row.last_used_at ? new Date(row.last_used_at).toLocaleString() : '';
        return `<button class="history-item" data-idx="${idx}" type="button">${topics}<span class="history-meta">Used ${count} times · ${ts}</span></button>`;
      }).join('');
      topicHistoryEl.querySelectorAll('.history-item').forEach(btn => {
        btn.addEventListener('click', () => {
          const row = rows[parseInt(btn.dataset.idx, 10)];
          if (!row || !row.topics) return;
          document.getElementById("topics").value = row.topics.join("\\n");
        });
      });
    }

    async function fetchTopicHistory() {
      const res = await fetch("/topic-history");
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to load topic history");
      renderTopicHistory(data.history || []);
    }

    async function fetchConfig() {
      const res = await fetch("/config");
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || "Failed to load config");
      const c = data.config;
      document.getElementById("topics").value = (c.topics || []).join("\\n");
      document.getElementById("max_results").value = c.max_results ?? 30;
      document.getElementById("top_k").value = 10;
      document.getElementById("min_relevance_score").value = c.min_relevance_score ?? 7.0;
      document.getElementById("fetch_multiplier").value = c.fetch_multiplier ?? 3;
      const recentDays = c.recent_days ?? 7;
      const preset = ["3", "7", "30"];
      if (preset.includes(String(recentDays))) {
        document.getElementById("recent_window").value = String(recentDays);
      } else {
        document.getElementById("recent_window").value = "custom";
        document.getElementById("recent_days_custom").value = String(recentDays);
      }
      setStatus("Config loaded. Edit topics and click 'Save + Retrieve Papers'.");
      await fetchTopicHistory();
    }

    function readInputs() {
      const topics = document.getElementById("topics").value
        .split("\\n")
        .map(v => v.trim())
        .filter(Boolean);
      return {
        topics,
        max_results: parseInt(document.getElementById("max_results").value || "30", 10),
        top_k: parseInt(document.getElementById("top_k").value || "10", 10),
        min_relevance_score: parseFloat(document.getElementById("min_relevance_score").value || "7.0"),
        fetch_multiplier: parseInt(document.getElementById("fetch_multiplier").value || "3", 10),
        recent_days:
          document.getElementById("recent_window").value === "custom"
            ? parseInt(document.getElementById("recent_days_custom").value || "14", 10)
            : parseInt(document.getElementById("recent_window").value, 10),
      };
    }

    async function runAgent() {
      runBtn.disabled = true;
      try {
        const input = readInputs();
        if (!input.topics.length) {
          throw new Error("Provide at least one topic.");
        }

        setStatus("Saving config...");
        const configRes = await fetch("/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            updates: {
              topics: input.topics,
              max_results: input.max_results,
              min_relevance_score: input.min_relevance_score,
              fetch_multiplier: input.fetch_multiplier,
              recent_days: input.recent_days,
            }
          }),
        });
        const configData = await configRes.json();
        if (!configData.ok) throw new Error(configData.error || "Failed to save config.");

        setStatus("Retrieving papers and generating report...");
        const runRes = await fetch("/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            top_k: input.top_k,
            recent_days_override: input.recent_days,
            force_open_report: false
          }),
        });
        const runData = await runRes.json();
        if (!runData.ok) throw new Error(runData.error || "Run failed.");

        const stamp = Date.now();
        reportFrame.src = `/report/latest?t=${stamp}`;
        setStatus(
          "Done. Report refreshed.\\n" +
          `Summary method: ${runData.result.summary_method}\\n` +
          `Markdown: ${runData.result.markdown_path}`
        );
        await fetchTopicHistory();
      } catch (err) {
        setStatus(`Error: ${err.message}`);
      } finally {
        runBtn.disabled = false;
      }
    }

    runBtn.addEventListener("click", runAgent);
    fetchConfig().catch((e) => setStatus(`Error: ${e.message}`));
  </script>
</body>
</html>
"""

REPORT_CSS_OVERRIDE = """
<style id="paper-agent-size-override">
  body { background: #ffffff !important; }
  main { max-width: 100%  !important; width: 100%  !important; padding: 0 !important; margin: 0 !important; }
  .report-shell {
    width: 100% !important;
    box-sizing: border-box !important;
    padding: 10px 12px 24px 12px !important;
    border: none !important;
    box-shadow: none !important;
  }
  h1 { font-size: 64px !important; margin-top: 0 !important; margin-bottom: 4px !important; }
  .sub { font-size: 24px !important; margin-top: 0 !important; margin-bottom: 8px !important; }
  .card {
    border-left: 6px solid #0d9488 !important;
    border-radius: 10px !important;
    padding: 14px 16px !important;
    margin-bottom: 12px !important;
    box-shadow: 0 6px 14px rgba(0, 0, 0, 0.05) !important;
  }
  h2 { font-size: 22px !important; }
  .meta { font-size: 14px !important; }
  .summary { font-size: 14px !important; line-height: 1.65 !important; white-space: normal !important; }
</style>
"""


def format_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        items = ", ".join(json.dumps(str(item)) for item in value)
        return f"[{items}]"
    raise TypeError(f"Unsupported config type: {type(value).__name__}")


def dump_config_toml(config: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in CONFIG_KEYS:
        if key in config:
            lines.append(f"{key} = {format_toml_value(config[key])}")
    return "\n".join(lines) + "\n"


def write_config(config_path: Path, config: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(dump_config_toml(config), encoding="utf-8")


def load_topic_history(limit: int = 20) -> list[dict[str, Any]]:
    if not TOPIC_HISTORY_PATH.exists():
        return []
    try:
        rows = json.loads(TOPIC_HISTORY_PATH.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            return []
        return rows[:limit]
    except Exception:
        return []


def save_topic_history(rows: list[dict[str, Any]], limit: int = 50) -> None:
    TOPIC_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOPIC_HISTORY_PATH.write_text(
        json.dumps(rows[:limit], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_topic_history(topics: list[str]) -> None:
    clean_topics = [str(t).strip() for t in topics if str(t).strip()]
    if not clean_topics:
        return
    signature = " || ".join(clean_topics).lower()
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = load_topic_history(limit=100)
    found_idx = None
    for i, row in enumerate(rows):
        if str(row.get("signature", "")) == signature:
            found_idx = i
            break
    if found_idx is not None:
        row = rows.pop(found_idx)
        row["last_used_at"] = now_iso
        row["count"] = int(row.get("count", 1)) + 1
        rows.insert(0, row)
    else:
        rows.insert(
            0,
            {
                "topics": clean_topics,
                "signature": signature,
                "last_used_at": now_iso,
                "count": 1,
            },
        )
    save_topic_history(rows, limit=50)


def with_report_css_override(html: str) -> str:
    if "paper-agent-size-override" in html:
        return html
    if "</head>" in html:
        return html.replace("</head>", REPORT_CSS_OVERRIDE + "\n</head>")
    return REPORT_CSS_OVERRIDE + html


class AgentApiHandler(BaseHTTPRequestHandler):
    server_version = "PaperAgentAPI/1.0"

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, status: int, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _config_path(self, body: dict[str, Any] | None = None) -> Path:
        if body and body.get("config_path"):
            return Path(str(body["config_path"]))
        return DEFAULT_CONFIG_PATH

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._send_html(200, WEB_DASHBOARD_HTML)
            return
        if path == "/health":
            self._send(200, {"ok": True})
            return
        if path == "/config":
            try:
                config = load_config(DEFAULT_CONFIG_PATH)
                self._send(200, {"ok": True, "config_path": str(DEFAULT_CONFIG_PATH), "config": config})
            except Exception as exc:
                self._send(400, {"ok": False, "error": str(exc)})
            return
        if path == "/topic-history":
            self._send(200, {"ok": True, "history": load_topic_history(limit=20)})
            return
        if path == "/report/latest":
            try:
                config = load_config(DEFAULT_CONFIG_PATH)
                report_dir = Path(str(config.get("report_dir", "reports")))
                latest = report_dir / "latest.html"
                if latest.exists():
                    raw = latest.read_text(encoding="utf-8")
                    self._send_html(200, with_report_css_override(raw))
                else:
                    self._send_html(
                        200,
                        "<html><body><p>No report yet. Run the agent from this dashboard.</p></body></html>",
                    )
            except Exception as exc:
                self._send_html(500, f"<html><body><p>Error loading report: {exc}</p></body></html>")
            return
        self._send(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            body = self._read_json()
        except Exception as exc:
            self._send(400, {"ok": False, "error": f"Invalid JSON: {exc}"})
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/config":
            config_path = self._config_path(body)
            updates = body.get("updates", {})
            if not isinstance(updates, dict):
                self._send(400, {"ok": False, "error": "'updates' must be an object"})
                return
            try:
                config = load_config(config_path)
                for key, value in updates.items():
                    if key not in CONFIG_KEYS:
                        self._send(400, {"ok": False, "error": f"Unknown config key: {key}"})
                        return
                    config[key] = value
                write_config(config_path, config)
                self._send(200, {"ok": True, "config_path": str(config_path), "config": config})
            except Exception as exc:
                self._send(400, {"ok": False, "error": str(exc)})
            return

        if path == "/run":
            config_path = self._config_path(body)
            max_results = body.get("max_results_override")
            recent_days_override = body.get("recent_days_override")
            top_k = int(body.get("top_k", 10))
            force_no_llm = bool(body.get("force_no_llm", False))
            force_open_report = bool(body.get("force_open_report", False))
            try:
                result = run_agent(
                    config_path=config_path,
                    max_results_override=max_results,
                    top_k=top_k,
                    recent_days_override=recent_days_override,
                    force_no_llm=force_no_llm,
                    force_open_report=force_open_report,
                    suppress_auto_open=True,
                )
                current_config = load_config(config_path)
                record_topic_history([str(t) for t in current_config.get("topics", [])])
                self._send(200, {"ok": True, "result": result})
            except Exception as exc:
                self._send(500, {"ok": False, "error": str(exc)})
            return

        self._send(404, {"ok": False, "error": "Not found"})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Paper agent local API server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), AgentApiHandler)
    print(f"Paper agent API listening on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
