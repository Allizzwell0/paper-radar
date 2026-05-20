import argparse
import csv
import json
import math
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"

KEYWORDS_FILE = CONFIG_DIR / "keywords.txt"
SEEN_FILE = DATA_DIR / "seen_papers.json"
CSV_OUTPUT = OUTPUT_DIR / "ranked_papers.csv"
MD_OUTPUT = OUTPUT_DIR / "latest_titles.md"


def read_keywords():
    if not KEYWORDS_FILE.exists():
        raise FileNotFoundError(f"Missing keywords file: {KEYWORDS_FILE}")
    keywords = []
    for line in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            keywords.append(line)
    if not keywords:
        raise ValueError("config/keywords.txt is empty.")
    return keywords


def load_seen():
    if not SEEN_FILE.exists():
        return {}
    return json.loads(SEEN_FILE.read_text(encoding="utf-8"))


def save_seen(seen):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def normalize_title(title):
    title = title or ""
    title = title.lower()
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def openalex_search(keyword, from_date, per_page=50):
    params = {
        "search": keyword,
        "filter": f"from_publication_date:{from_date}",
        "per-page": per_page,
        "sort": "publication_date:desc",
    }

    mailto = os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto

    url = "https://api.openalex.org/works?" + urlencode(params)
    req = Request(url, headers={"User-Agent": "paper-radar/0.1"})

    with urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    return data.get("results", [])


def extract_work(work, keyword):
    title = work.get("display_name") or ""
    doi = work.get("doi") or ""
    publication_date = work.get("publication_date") or ""
    cited_by_count = work.get("cited_by_count") or 0
    fwci = work.get("fwci")
    is_retracted = work.get("is_retracted") or False

    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    journal = source.get("display_name") or "未找到"

    open_access = work.get("open_access") or {}
    is_oa = open_access.get("is_oa")

    return {
        "title": title,
        "normalized_title": normalize_title(title),
        "doi": doi,
        "publication_date": publication_date,
        "journal": journal,
        "cited_by_count": cited_by_count,
        "fwci": fwci,
        "is_retracted": is_retracted,
        "is_open_access": is_oa,
        "matched_keyword": keyword,
        "openalex_id": work.get("id") or "",
    }


def relevance_score(title, keyword):
    title_norm = normalize_title(title)
    terms = [t for t in normalize_title(keyword).split() if len(t) > 2]
    if not terms:
        return 0.0
    hits = sum(1 for term in terms if term in title_norm)
    phrase_hit = 1 if normalize_title(keyword) in title_norm else 0
    return min(1.0, (hits / len(terms)) * 0.75 + phrase_hit * 0.25)


def recency_score(publication_date, days):
    try:
        d = date.fromisoformat(publication_date)
    except Exception:
        return 0.0
    age = (date.today() - d).days
    if age < 0:
        return 0.0
    return max(0.0, 1.0 - age / max(days, 1))


def score_paper(paper, days):
    rel = relevance_score(paper["title"], paper["matched_keyword"])
    citation = min(1.0, math.log1p(paper["cited_by_count"]) / math.log1p(500))
    recency = recency_score(paper["publication_date"], days)
    oa = 1.0 if paper["is_open_access"] else 0.0

    # Journal impact factor is intentionally not used in v0.
    # Add config/journal_metrics.csv later if you have JCR or Scopus metrics.
    journal_metric = 0.0

    return (
        0.40 * rel
        + 0.25 * citation
        + 0.20 * recency
        + 0.10 * journal_metric
        + 0.05 * oa
    )


def dedupe(papers):
    seen_keys = set()
    deduped = []

    for paper in papers:
        key = paper["doi"] or paper["normalized_title"]
        if not key:
            continue
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(paper)

    return deduped


def write_outputs(papers, title_only=False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fields = [
        "score",
        "title",
        "doi",
        "publication_date",
        "journal",
        "cited_by_count",
        "fwci",
        "is_open_access",
        "matched_keyword",
        "openalex_id",
    ]

    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            writer.writerow({field: paper.get(field, "") for field in fields})

    lines = []
    lines.append("# Paper Radar Latest Results")
    lines.append("")

    for i, paper in enumerate(papers, start=1):
        if title_only:
            lines.append(f"{i}. {paper['title']}")
            if paper.get("doi"):
                lines.append(f"   DOI: {paper['doi']}")
            continue

        lines.append(f"## {i}. {paper['title']}")
        lines.append("")
        lines.append(f"- DOI: {paper.get('doi') or '未找到'}")
        lines.append(f"- Journal: {paper.get('journal') or '未找到'}")
        lines.append(f"- Date: {paper.get('publication_date') or '未找到'}")
        lines.append(f"- Citations: {paper.get('cited_by_count', 0)}")
        lines.append(f"- FWCI: {paper.get('fwci') if paper.get('fwci') is not None else '未找到'}")
        lines.append(f"- Matched keyword: {paper.get('matched_keyword')}")
        lines.append(f"- Score: {paper.get('score'):.4f}")
        lines.append("")

    MD_OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--title-only", action="store_true")
    parser.add_argument("--include-seen", action="store_true")
    args = parser.parse_args()

    keywords = read_keywords()
    from_date = (date.today() - timedelta(days=args.days)).isoformat()

    all_papers = []
    for keyword in keywords:
        print(f"Searching OpenAlex: {keyword}")
        try:
            works = openalex_search(keyword, from_date)
        except Exception as exc:
            print(f"Warning: failed to search keyword '{keyword}': {exc}")
            continue

        for work in works:
            paper = extract_work(work, keyword)
            if paper["is_retracted"]:
                continue
            if not paper["title"]:
                continue
            all_papers.append(paper)

        time.sleep(0.5)

    papers = dedupe(all_papers)
    seen = load_seen()

    if not args.include_seen:
        fresh = []
        for paper in papers:
            key = paper["doi"] or paper["normalized_title"]
            if key not in seen:
                fresh.append(paper)
        papers = fresh

    for paper in papers:
        paper["score"] = score_paper(paper, args.days)

    papers.sort(key=lambda p: p["score"], reverse=True)
    papers = papers[:args.top]

    write_outputs(papers, title_only=args.title_only)

    for paper in papers:
        key = paper["doi"] or paper["normalized_title"]
        seen[key] = {
            "title": paper["title"],
            "doi": paper["doi"],
            "first_seen": date.today().isoformat(),
        }
    save_seen(seen)

    print(f"Done. Wrote: {CSV_OUTPUT}")
    print(f"Done. Wrote: {MD_OUTPUT}")


if __name__ == "__main__":
    main()
