# Paper Agent (arXiv)

Automatically fetches recent arXiv papers for configured topics and writes Markdown + HTML summary reports.
Each paper is summarized by an LLM (with extractive fallback).

## Setup

```bash
pip install -r requirements.txt
```

## Configure topics

Edit:

- `paper_agent/config.toml`

Example:

```toml
topics = ["large language models", "multimodal learning"]
max_results = 30
report_dir = "reports"
report_name_prefix = "arxiv_topic_report"
llm_enabled = true
llm_model = "gpt-4.1-mini"
llm_api_key_env = "OPENAI_API_KEY"
llm_max_output_tokens = 220
html_enabled = true
auto_open_html = true
fetch_multiplier = 3
max_fetch_cap = 200
min_relevance_score = 7.0
recent_days = 7
arxiv_timeout_seconds = 60
arxiv_max_retries = 5
arxiv_backoff_base_seconds = 2.0
arxiv_user_agent = "paper-agent/1.0 (research automation; contact: local-user)"
```

Set your API key (if using LLM summaries):

```bash
export OPENAI_API_KEY="your_api_key_here"
```

## Run

```bash
python -m paper_agent.agent --config paper_agent/config.toml --top-k 10
```

Example with explicit time window:

```bash
python -m paper_agent.agent --config paper_agent/config.toml --top-k 10 --recent-days 3
```

This generates a report file under `reports/`.
It also writes `reports/latest.html` and opens it in your browser when `auto_open_html = true`.

To disable LLM summaries:

```bash
python -m paper_agent.agent --config paper_agent/config.toml --top-k 10 --no-llm
```

To open HTML report once from CLI (regardless of config):

```bash
python -m paper_agent.agent --config paper_agent/config.toml --top-k 10 --open-report
```

## Local config API

Start API server:

```bash
python -m paper_agent.api --host 127.0.0.1 --port 8765
```

Open interactive dashboard in browser:

```text
http://127.0.0.1:8765/
```

In the dashboard you can:
- edit topics
- reuse recent searched topics from history
- tune retrieval params (`max_results`, `top_k`, relevance threshold)
- choose a publish window (`3 days`, `1 week`, `1 month`, or custom days)
- click `Save + Retrieve Papers`
- view refreshed report directly in the embedded preview

Read config:

```bash
curl http://127.0.0.1:8765/config
```

Trigger a run and open local report:

```bash
curl -X POST http://127.0.0.1:8765/run \
  -H "Content-Type: application/json" \
  -d '{"top_k": 10, "force_open_report": true}'
```

Retrieval tuning:

- `fetch_multiplier`: fetch extra candidates before ranking/filtering.
- `max_fetch_cap`: hard upper bound for fetched candidates.
- `min_relevance_score`: drop low-alignment papers from final report.
- `recent_days`: include only papers published in the last N days.
- `arxiv_timeout_seconds`: per-request timeout to arXiv API.
- `arxiv_max_retries`: retry count for timeout/429/5xx errors.
- `arxiv_backoff_base_seconds`: exponential backoff base delay.
- `arxiv_user_agent`: custom user-agent for arXiv etiquette.

## Automate

Run every day at 9:00 AM via cron:

```bash
0 9 * * * python3 -m paper_agent.agent --config paper_agent/config.toml --top-k 10
```

## Deploy to GitHub Pages

This repo includes:

- `.github/workflows/deploy-pages.yml`

It runs on a daily schedule and manual trigger, generates `reports/latest.html`, then deploys it to GitHub Pages as `index.html`.
It now deploys:
- `index.html`: a static dashboard shell page
- `latest.html`: latest generated report (embedded in `index.html`)

Enable in GitHub:

1. Push this repository to GitHub.
2. Open repository settings:
   - `Settings -> Pages -> Source: GitHub Actions`
3. Open `Actions` tab and run `Deploy Paper Report to GitHub Pages` once.
4. Your report page will be available at:
   - `https://<your-username>.github.io/<repo-name>/`

Note:
- GitHub Pages is static hosting. The interactive local APIs (`/config`, `/run`) are not available on Pages.
- Use local dashboard (`http://127.0.0.1:8765/`) for interactive runs; Pages is for public viewing.
