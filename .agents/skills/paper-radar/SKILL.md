---
name: paper-radar
description: use this skill when the user asks to monitor, discover, rank, summarize, or update recent academic papers by keywords. this skill retrieves recent papers from scholarly sources, deduplicates results, scores papers by keyword relevance, citations, recency, journal metrics when available, and outputs a concise ranked list of paper titles with doi and search metadata.
---

# Paper Radar

## Goal

Help the user monitor recent academic papers by keywords and produce a ranked list of titles for manual follow-up search.

## Default behavior

1. Read runtime settings from `config/settings.json`.
2. Read keywords from `config/keywords.txt` unless the user provides keywords directly.
3. Search recent papers from OpenAlex and Semantic Scholar.
4. Deduplicate by DOI and normalized title.
5. Match `config/journal_metrics.csv` by ISSN first and journal name second.
6. Exclude retracted papers when metadata is available.
7. Rank papers by keyword relevance, citation count, recency, journal metric, and open-access availability.
8. When `deepseek_summaries` is enabled, call DeepSeek to generate Chinese summaries with content overview, innovation, value, and caveats.
9. Save machine-readable results to `outputs/ranked_papers.csv`.
10. Save Markdown results to `outputs/latest_titles.md` and `outputs/latest_titles_title_only.md`.

## Output style

- Use Chinese by default.
- Keep the final message concise.
- Default output should include title, DOI, journal, date, citation count, source, score, and available journal metrics.
- If the user asks for title-only mode, output paper titles, DOI, and the DeepSeek Chinese summary when available.
- Never treat journal impact factor as the only quality metric.
- Mark unavailable metrics as `未找到`, not guessed.

## Commands

Run the main workflow with:

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py
```

Override settings with:

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --days 30 --top 30 --min-score 0.2 --deepseek-summary
```
