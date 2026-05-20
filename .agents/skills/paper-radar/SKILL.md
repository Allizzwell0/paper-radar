@"
---
name: paper-radar
description: use this skill when the user asks to monitor, discover, rank, summarize, or update recent academic papers by keywords. this skill retrieves recent papers from scholarly sources, deduplicates results, scores papers by keyword relevance, citations, recency, journal metrics when available, and outputs a concise ranked list of paper titles with doi and search metadata.
---

# Paper Radar

## Goal

Help the user monitor recent academic papers by keywords and produce a ranked list of titles for manual follow-up search.

## Default behavior

1. Read keywords from `config/keywords.txt` unless the user provides keywords directly.
2. Search recent papers from scholarly APIs.
3. Deduplicate by DOI and normalized title.
4. Exclude retracted papers when metadata is available.
5. Rank papers by:
   - keyword relevance
   - citation count
   - recency
   - journal metric if available
   - open-access availability if available
6. Save machine-readable results to `outputs/ranked_papers.csv`.
7. Save concise title output to `outputs/latest_titles.md`.

## Output style

- Use Chinese by default.
- Keep the final message concise.
- Default output should include title, DOI, journal, date, citation count, and one ranking reason.
- If the user asks for title-only mode, output only paper titles and DOI.
- Never treat journal impact factor as the only quality metric.
- Mark unavailable metrics as `未找到`, not guessed.

## Commands

Run the main workflow with:

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --days 30 --top 30