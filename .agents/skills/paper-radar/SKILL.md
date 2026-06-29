---
name: paper-radar
description: use this skill when the user asks to monitor, discover, rank, summarize, export, or update recent academic papers by topics or keywords. this skill retrieves papers from OpenAlex, Semantic Scholar, and arXiv; deduplicates results; scores papers by relevance, citations, recency, journal metrics, and open access; summarizes with DeepSeek when configured; and exports ranked Markdown/CSV plus Zotero and Obsidian artifacts.
---

# Paper Radar

## Goal

Help the user monitor recent academic papers by topic, rank them for follow-up reading, and produce workflow-ready outputs for Markdown review, Zotero import, and Obsidian notes.

## Default behavior

1. Run the main workflow with `python .agents\skills\paper-radar\scripts\paper_radar.py`.
2. Read public settings from `config/settings.json`, then local private overrides from ignored `config/settings.local.json`.
3. Read topics from `config/topics.yaml`; if missing, fall back to `config/keywords.txt`.
4. Search OpenAlex, Semantic Scholar, and arXiv when enabled.
5. Normalize paper fields across sources, including title, authors, abstract, DOI, arXiv ID, source IDs, venue, dates, URL, PDF URL, citations, source list, matched keywords, topic metadata, and summary fields.
6. Deduplicate by DOI, arXiv ID, Semantic Scholar ID, OpenAlex ID, then normalized title.
7. Match `config/journal_metrics.csv` by ISSN first and journal name second.
8. Exclude retracted papers when metadata is available, configured work types/title patterns, and topic-level `exclude_keywords`.
9. Rank papers by keyword relevance, citation count, recency, journal metric, and open-access availability.
10. Filter low-relevance papers with `min_relevance`; relevance combines title and abstract matching and should carry the largest score weight by default.
11. When `deepseek_summaries` is enabled, call DeepSeek using `deepseek_base_url`, `deepseek_api_key`, model, timeout, sampling, JSON-mode, and cache settings to generate Chinese summaries.
12. When `deepseek_json_output` is enabled, parse structured summary keys and keep raw text if JSON parsing fails.
13. Save core outputs to `outputs/ranked_papers.csv`, `outputs/latest_titles.md`, and `outputs/latest_titles_title_only.md`.
14. When enabled, save Zotero review/import files to `outputs/zotero_review_queue.csv` and `outputs/zotero_import.bib`.
15. When enabled, save Obsidian notes either under `outputs/obsidian/` or the configured vault path.
16. Respect `--dry-run`: do not update `data/seen_papers.json` and do not write to a real Obsidian vault.
17. Write run logs to the configured `log_file`, defaulting to `outputs/run_log.txt`.

## Output style

- Use Chinese by default.
- Keep final user messages concise.
- Default result summaries should mention title, DOI/arXiv ID, journal or venue, date, citation count, source, score, relevance, and available journal metrics.
- In title-only mode, include title, DOI/arXiv ID, topic, and the DeepSeek Chinese summary when available.
- Never treat journal impact factor as the only quality metric.
- Mark unavailable metrics as `未找到`, not guessed.

## Commands

Run with config:

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py
```

Fast dry-run without LLM:

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --dry-run --no-deepseek-summary --top 10
```

Common overrides:

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --days 365 --top 30 --min-score 0 --arxiv --deepseek-json
```
