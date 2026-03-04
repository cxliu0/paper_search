from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import re
import sys
import textwrap
import time
import webbrowser
try:
    import tomllib
except ModuleNotFoundError:  # Python <3.11
    import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote_plus
from xml.etree import ElementTree

import requests


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
DEFAULT_ARXIV_USER_AGENT = "paper-agent/1.0 (research automation; contact: local-user)"
STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "of",
    "to",
    "in",
    "for",
    "on",
    "with",
    "from",
    "by",
    "using",
    "via",
    "based",
    "at",
    "is",
    "are",
}


@dataclass
class Author:
    name: str


@dataclass
class Paper:
    title: str
    summary: str
    authors: list[Author]
    published: dt.datetime
    updated: dt.datetime
    link: str
    categories: list[str]


@dataclass
class ReportEntry:
    paper: Paper
    summary: str
    score: float
    matched_terms: list[str]


def load_config(config_path: Path) -> dict:
    with config_path.open("rb") as f:
        config = tomllib.load(f)

    required = ["topics"]
    missing = [k for k in required if k not in config]
    if missing:
        raise ValueError(f"Missing required config keys: {missing}")

    if not isinstance(config["topics"], list) or not config["topics"]:
        raise ValueError("'topics' must be a non-empty list in config.")

    config.setdefault("max_results", 25)
    config.setdefault("report_dir", "reports")
    config.setdefault("report_name_prefix", "arxiv_report")
    config.setdefault("llm_enabled", True)
    config.setdefault("llm_model", "gpt-4.1-mini")
    config.setdefault("llm_api_key_env", "OPENAI_API_KEY")
    config.setdefault("llm_max_output_tokens", 220)
    config.setdefault("html_enabled", True)
    config.setdefault("auto_open_html", False)
    config.setdefault("fetch_multiplier", 3)
    config.setdefault("max_fetch_cap", 200)
    config.setdefault("min_relevance_score", 7.0)
    config.setdefault("recent_days", 7)
    config.setdefault("arxiv_timeout_seconds", 60)
    config.setdefault("arxiv_max_retries", 5)
    config.setdefault("arxiv_backoff_base_seconds", 2.0)
    config.setdefault("arxiv_user_agent", DEFAULT_ARXIV_USER_AGENT)
    return config


def build_search_query(topics: Iterable[str]) -> str:
    terms: list[str] = []
    for topic in topics:
        topic_clean = clean_whitespace(topic).lower()
        if not topic_clean:
            continue
        tokens = [t for t in tokenize_text(topic_clean) if len(t) > 2 and t not in STOPWORDS]
        phrase_clause = f'(ti:"{topic_clean}" OR abs:"{topic_clean}")'
        if len(tokens) >= 2:
            token_clause = " AND ".join([f"(ti:{t} OR abs:{t})" for t in tokens[:4]])
            terms.append(f"({phrase_clause} OR ({token_clause}))")
        else:
            terms.append(phrase_clause)
    if not terms:
        raise ValueError("No valid topics provided.")
    return " OR ".join(terms)


def fetch_arxiv_papers(
    search_query: str,
    max_results: int = 25,
    timeout_seconds: int = 60,
    max_retries: int = 5,
    backoff_base_seconds: float = 2.0,
    user_agent: str = DEFAULT_ARXIV_USER_AGENT,
) -> list[Paper]:
    query = quote_plus(search_query)
    url = (
        f"{ARXIV_API_URL}?search_query={query}&start=0"
        f"&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    )
    headers = {"User-Agent": user_agent}

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, timeout=timeout_seconds, headers=headers)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait_s = float(retry_after)
                else:
                    wait_s = backoff_base_seconds * (2**attempt)
                time.sleep(min(wait_s, 90.0))
                continue
            response.raise_for_status()
            return parse_arxiv_feed(response.text)
        except (requests.ReadTimeout, requests.ConnectTimeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            wait_s = backoff_base_seconds * (2**attempt)
            time.sleep(min(wait_s, 90.0))
            continue
        except requests.HTTPError as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            # Retry transient gateway/service errors.
            if exc.response is not None and exc.response.status_code in {500, 502, 503, 504}:
                wait_s = backoff_base_seconds * (2**attempt)
                time.sleep(min(wait_s, 90.0))
                continue
            break

    if last_error:
        raise last_error
    raise RuntimeError("Failed to fetch arXiv papers for unknown reason.")


def filter_papers_by_recent_days(papers: list[Paper], recent_days: int | None) -> list[Paper]:
    if recent_days is None:
        return papers
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max(int(recent_days), 0))
    return [paper for paper in papers if paper.published >= cutoff]


def parse_dt(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_arxiv_feed(atom_xml: str) -> list[Paper]:
    root = ElementTree.fromstring(atom_xml)
    papers: list[Paper] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS)).strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=ATOM_NS)).strip()
        published = parse_dt(entry.findtext("atom:published", default="", namespaces=ATOM_NS))
        updated = parse_dt(entry.findtext("atom:updated", default="", namespaces=ATOM_NS))

        authors: list[Author] = []
        for author in entry.findall("atom:author", ATOM_NS):
            name = (author.findtext("atom:name", default="", namespaces=ATOM_NS)).strip()
            authors.append(Author(name=name))

        categories = [c.attrib.get("term", "") for c in entry.findall("atom:category", ATOM_NS)]
        link = ""
        for item in entry.findall("atom:link", ATOM_NS):
            if item.attrib.get("rel") == "alternate":
                link = item.attrib.get("href", "")
                break

        papers.append(
            Paper(
                title=clean_whitespace(title),
                summary=clean_whitespace(summary),
                authors=authors,
                published=published,
                updated=updated,
                link=link,
                categories=categories,
            )
        )

    return papers


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def tokenize_text(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def collect_topic_terms(topics: Iterable[str]) -> list[str]:
    terms: set[str] = set()
    for topic in topics:
        topic_clean = clean_whitespace(topic).lower()
        if topic_clean:
            terms.add(topic_clean)
        for token in tokenize_text(topic_clean):
            if len(token) > 2 and token not in STOPWORDS:
                terms.add(token)
    return sorted(terms)


def summarize_abstract(abstract: str) -> str:
    return clean_whitespace(abstract) if clean_whitespace(abstract) else "No abstract provided."


def build_summary_fn(
    config: dict, topics: list[str], max_sentences: int = 2
) -> tuple[Callable[[Paper], str], str]:
    _ = (config, topics, max_sentences)
    return (lambda paper: summarize_abstract(paper.summary), "abstract")


def score_paper_for_topics(paper: Paper, topics: Iterable[str]) -> float:
    title = clean_whitespace(paper.title).lower()
    abstract = clean_whitespace(paper.summary).lower()
    categories = " ".join(paper.categories).lower()
    full_text = f"{title} {abstract} {categories}"

    topic_phrases = [clean_whitespace(t).lower() for t in topics if clean_whitespace(t)]
    topic_tokens = [t for t in collect_topic_terms(topics) if " " not in t]
    if not topic_tokens and not topic_phrases:
        return 0.0

    full_tokens = set(tokenize_text(full_text))
    title_tokens = set(tokenize_text(title))
    token_total = max(len(topic_tokens), 1)
    overlap_full = sum(1 for token in topic_tokens if token in full_tokens)
    overlap_title = sum(1 for token in topic_tokens if token in title_tokens)
    phrase_hits_title = sum(1 for phrase in topic_phrases if phrase in title)
    phrase_hits_abstract = sum(1 for phrase in topic_phrases if phrase in abstract)

    score = 0.0
    score += 14.0 * phrase_hits_title
    score += 8.0 * phrase_hits_abstract
    score += 22.0 * (overlap_full / token_total)
    score += 8.0 * (overlap_title / token_total)

    days_old = max((dt.datetime.now(dt.timezone.utc) - paper.published).days, 0)
    score += max(0.0, 3.0 - math.log10(days_old + 1))
    return round(score, 2)


def extract_matched_terms(paper: Paper, topics: Iterable[str], max_terms: int = 8) -> list[str]:
    text = f"{paper.title} {paper.summary} {' '.join(paper.categories)}".lower()
    matched = [term for term in collect_topic_terms(topics) if term in text]
    return matched[:max_terms]


def format_author_names(authors: list[Author], limit: int = 5) -> str:
    names = [a.name for a in authors if a.name]
    author_text = ", ".join(names[:limit])
    if len(names) > limit:
        author_text += ", et al."
    return author_text or "N/A"


def build_report_entries(
    papers: list[Paper],
    topics: list[str],
    summary_fn: Callable[[Paper], str],
    min_relevance_score: float,
    top_k: int = 10,
) -> list[ReportEntry]:
    scored = [(paper, score_paper_for_topics(paper, topics)) for paper in papers]
    sorted_papers = sorted(
        scored,
        key=lambda item: (item[1], item[0].published),
        reverse=True,
    )
    selected = [item for item in sorted_papers if item[1] >= min_relevance_score][:top_k]
    entries: list[ReportEntry] = []
    for paper, score in selected:
        entries.append(
            ReportEntry(
                paper=paper,
                summary=summary_fn(paper),
                score=score,
                matched_terms=extract_matched_terms(paper, topics),
            )
        )
    return entries


def generate_markdown_report(
    entries: list[ReportEntry],
    topics: list[str],
    summary_method: str,
    total_fetched: int,
    min_relevance_score: float,
    recent_days: int | None,
) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# arXiv Topic Report ({now})",
        "",
        f"Topics: {', '.join(topics)}",
        f"Total fetched: {total_fetched}",
        f"Top included: {len(entries)}",
        f"Summary method: {summary_method}",
        f"Min relevance score: {min_relevance_score}",
        f"Time window: last {recent_days} day(s)" if recent_days is not None else "Time window: all time",
        "",
    ]

    if not entries:
        lines.append("No papers found.")
        return "\n".join(lines)

    for idx, entry in enumerate(entries, 1):
        paper = entry.paper
        author_text = format_author_names(paper.authors)
        lines.extend(
            [
                f"## {idx}. {paper.title}",
                f"- Relevance score: {entry.score}",
                f"- Matched terms: {', '.join(entry.matched_terms) if entry.matched_terms else 'N/A'}",
                f"- Published: {paper.published.date().isoformat()}",
                f"- Authors: {author_text}",
                f"- Categories: {', '.join(paper.categories) if paper.categories else 'N/A'}",
                f"- Link: {paper.link or 'N/A'}",
                "- Summary:",
                textwrap.fill(clean_whitespace(entry.summary), width=100),
                "",
            ]
        )

    return "\n".join(lines)


def generate_html_report(
    entries: list[ReportEntry], topics: list[str], summary_method: str, total_fetched: int
) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    cards: list[str] = []
    for idx, entry in enumerate(entries, 1):
        paper = entry.paper
        author_text = format_author_names(paper.authors)
        categories = ", ".join(paper.categories) if paper.categories else "N/A"
        summary_html = clean_whitespace(entry.summary)
        cards.append(
            f"""
            <article class="card">
              <h2>{idx}. {paper.title}</h2>
              <p class="meta"><strong>Relevance:</strong> {entry.score} | <strong>Published:</strong> {paper.published.date().isoformat()}</p>
              <p class="meta"><strong>Matched terms:</strong> {', '.join(entry.matched_terms) if entry.matched_terms else 'N/A'}</p>
              <p class="meta"><strong>Authors:</strong> {author_text}</p>
              <p class="meta"><strong>Categories:</strong> {categories}</p>
              <p class="meta"><strong>Link:</strong> <a href="{paper.link}" target="_blank" rel="noreferrer">{paper.link}</a></p>
              <p class="summary">{summary_html}</p>
            </article>
            """
        )

    cards_html = "\n".join(cards) if cards else "<p>No papers found.</p>"
    topics_text = ", ".join(topics)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>arXiv Topic Report</title>
  <style>
    :root {{
      --bg: #f5f5f0;
      --paper: #ffffff;
      --text: #1b1f24;
      --accent: #0d9488;
      --muted: #4b5563;
      --border: #d6d3d1;
    }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--text);
      background: radial-gradient(circle at 10% 20%, #e6fffb, transparent 30%), var(--bg);
    }}
    main {{
      max-width: 2400px;
      width: calc(100vw - 24px);
      margin: 0 auto;
      padding: 0;      
    }}
    .report-shell {{
      background: #ffffff;
      border: none;
      border-radius: 0;
      width: 100% !important;
      max-width: 100% !important;
      box-sizing: border-box;
      padding: 10px 12px 24px;
      box-shadow: none;
    }}
    h1 {{
      margin-top: 0;
      margin-bottom: 4px;
      font-size: 50px;
      line-height: 1.1;
      letter-spacing: -0.8px;
    }}
    .sub {{
      color: var(--muted);
      margin-top: 0;
      margin-bottom: 8px;
      font-size: 24px;
    }}
    .card {{
      background: var(--paper);
      border: 1px solid var(--border);
      border-left: 6px solid var(--accent);
      border-radius: 10px;
      padding: 14px 16px;
      margin-bottom: 12px;
      box-shadow: 0 6px 14px rgba(0, 0, 0, 0.05);
    }}
    h2 {{
      margin: 0 0 8px;
      font-size: 22px;
      line-height: 1.3;
    }}
    .meta {{
      margin: 4px 0;
      color: #374151;
      font-size: 14px;
    }}
    .summary {{
      margin-top: 10px;
      line-height: 1.65;
      font-size: 14px;
      white-space: normal;
      text-align: left;
    }}
    a {{
      color: #0f766e;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <main>
    <section class="report-shell">
      <h1>arXiv Topic Report</h1>
      <p class="sub">{now} | Topics: {topics_text}</p>
      <p class="sub">Total fetched: {total_fetched} | Included: {len(entries)} | Summary method: {summary_method}</p>
      {cards_html}
    </section>
  </main>
</body>
</html>"""


def write_report(report_text: str, report_dir: Path, name_prefix: str, ext: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"{name_prefix}_{stamp}.{ext}"
    report_path.write_text(report_text, encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and summarize recent arXiv papers by topic.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("paper_agent/config.toml"),
        help="Path to TOML config file.",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Override max results from config.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="How many papers to include in the report.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM summaries and use extractive summaries.",
    )
    parser.add_argument(
        "--open-report",
        action="store_true",
        help="Open generated HTML report in default browser.",
    )
    parser.add_argument(
        "--recent-days",
        type=int,
        default=None,
        help="Only include papers published in the last N days (e.g., 3, 7, 30).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_agent(
            config_path=args.config,
            max_results_override=args.max_results,
            top_k=args.top_k,
            recent_days_override=args.recent_days,
            force_no_llm=args.no_llm,
            force_open_report=args.open_report,
        )
    except requests.RequestException as exc:
        print(f"Failed to fetch arXiv feed: {exc}", file=sys.stderr)
        print("Check internet/DNS access and try again.", file=sys.stderr)
        raise SystemExit(1)

    print(f"Markdown report generated: {Path(result['markdown_path']).resolve()}")
    if result.get("html_path"):
        print(f"HTML report generated: {Path(result['html_path']).resolve()}")
        print(f"Latest HTML: {Path(result['latest_html_path']).resolve()}")
        if result.get("opened_report"):
            print("Opened latest HTML report in browser.")


def run_agent(
    config_path: Path,
    max_results_override: int | None = None,
    top_k: int = 10,
    recent_days_override: int | None = None,
    force_no_llm: bool = False,
    force_open_report: bool = False,
    suppress_auto_open: bool = False,
) -> dict[str, str | bool]:
    config = load_config(config_path)
    topics = [str(t) for t in config["topics"]]
    max_results = max_results_override or int(config["max_results"])
    recent_days = (
        int(recent_days_override)
        if recent_days_override is not None
        else int(config.get("recent_days", 7))
    )
    fetch_multiplier = max(int(config.get("fetch_multiplier", 3)), 1)
    max_fetch_cap = max(int(config.get("max_fetch_cap", 200)), 1)
    min_relevance_score = float(config.get("min_relevance_score", 7.0))
    arxiv_timeout_seconds = int(config.get("arxiv_timeout_seconds", 60))
    arxiv_max_retries = int(config.get("arxiv_max_retries", 5))
    arxiv_backoff_base_seconds = float(config.get("arxiv_backoff_base_seconds", 2.0))
    arxiv_user_agent = str(config.get("arxiv_user_agent", DEFAULT_ARXIV_USER_AGENT))
    fetch_count = min(max_results * fetch_multiplier, max_fetch_cap)
    report_dir = Path(str(config["report_dir"]))
    name_prefix = str(config["report_name_prefix"])
    if force_no_llm:
        config["llm_enabled"] = False

    search_query = build_search_query(topics)
    papers = fetch_arxiv_papers(
        search_query,
        max_results=fetch_count,
        timeout_seconds=arxiv_timeout_seconds,
        max_retries=arxiv_max_retries,
        backoff_base_seconds=arxiv_backoff_base_seconds,
        user_agent=arxiv_user_agent,
    )
    papers = filter_papers_by_recent_days(papers, recent_days)

    summary_fn, summary_method = build_summary_fn(config, topics)
    entries = build_report_entries(
        papers,
        topics,
        summary_fn=summary_fn,
        min_relevance_score=min_relevance_score,
        top_k=top_k,
    )
    md_report = generate_markdown_report(
        entries=entries,
        topics=topics,
        summary_method=summary_method,
        total_fetched=len(papers),
        min_relevance_score=min_relevance_score,
        recent_days=recent_days,
    )
    md_path = write_report(md_report, report_dir=report_dir, name_prefix=name_prefix, ext="md")

    result: dict[str, str | bool] = {
        "markdown_path": str(md_path.resolve()),
        "summary_method": summary_method,
    }

    html_enabled = bool(config.get("html_enabled", True))
    auto_open_html = (
        (bool(config.get("auto_open_html", False)) and not suppress_auto_open)
        or force_open_report
    )
    if html_enabled:
        html_report = generate_html_report(
            entries=entries,
            topics=topics,
            summary_method=summary_method,
            total_fetched=len(papers),
        )
        html_path = write_report(html_report, report_dir=report_dir, name_prefix=name_prefix, ext="html")
        latest_html_path = report_dir / "latest.html"
        latest_html_path.write_text(html_report, encoding="utf-8")
        result["html_path"] = str(html_path.resolve())
        result["latest_html_path"] = str(latest_html_path.resolve())
        if auto_open_html:
            webbrowser.open(latest_html_path.resolve().as_uri())
            result["opened_report"] = True
        else:
            result["opened_report"] = False

    return result


if __name__ == "__main__":
    main()
