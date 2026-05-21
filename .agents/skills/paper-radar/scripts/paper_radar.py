import argparse
import csv
import html
import json
import math
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"

KEYWORDS_FILE = CONFIG_DIR / "keywords.txt"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LOCAL_SETTINGS_FILE = CONFIG_DIR / "settings.local.json"
JOURNAL_METRICS_FILE = CONFIG_DIR / "journal_metrics.csv"
SEEN_FILE = DATA_DIR / "seen_papers.json"
SUMMARY_CACHE_FILE = DATA_DIR / "deepseek_summaries.json"
LEGACY_SUMMARY_CACHE_FILE = DATA_DIR / "gpt_summaries.json"
CSV_OUTPUT = OUTPUT_DIR / "ranked_papers.csv"
MD_OUTPUT = OUTPUT_DIR / "latest_titles.md"
TITLE_ONLY_OUTPUT = OUTPUT_DIR / "latest_titles_title_only.md"

USER_AGENT = "paper-radar/1.0"
DEFAULT_SETTINGS = {
    "days": 30,
    "top": 30,
    "title_only": False,
    "min_score": 0.0,
    "include_seen": False,
    "request_timeout_seconds": 30,
    "source_sleep_seconds": 0.5,
    "user_agent": USER_AGENT,
    "openalex_enabled": True,
    "openalex_per_page": 50,
    "openalex_mailto": "",
    "semantic_scholar_enabled": True,
    "semantic_scholar_per_page": 50,
    "semantic_scholar_api_key": "",
    "deepseek_summaries": True,
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-v4-flash",
    "deepseek_summary_max_tokens": 500,
    "deepseek_temperature": 0.2,
    "deepseek_top_p": 1.0,
    "deepseek_timeout_seconds": 90,
    "deepseek_sleep_seconds": 0.3,
    "deepseek_cache_enabled": True,
    "deepseek_thinking_disabled": True,
}
MISSING = "未找到"


def read_keywords():
    if not KEYWORDS_FILE.exists():
        raise FileNotFoundError(f"Missing keywords file: {KEYWORDS_FILE}")
    keywords = []
    for line in KEYWORDS_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().lstrip("\ufeff")
        if line and not line.startswith("#"):
            keywords.append(line)
    if not keywords:
        raise ValueError("config/keywords.txt is empty.")
    return keywords


def load_settings(settings_file=SETTINGS_FILE, local_settings_file=LOCAL_SETTINGS_FILE):
    settings = DEFAULT_SETTINGS.copy()
    settings = merge_settings_file(settings, settings_file, required=False)
    settings = merge_settings_file(settings, local_settings_file, required=False)

    settings["days"] = positive_int(settings["days"], "days")
    settings["top"] = positive_int(settings["top"], "top")
    settings["title_only"] = parse_bool(settings["title_only"], "title_only")
    settings["include_seen"] = parse_bool(settings["include_seen"], "include_seen")
    settings["min_score"] = float(settings["min_score"])
    if settings["min_score"] < 0:
        raise ValueError("min_score must be greater than or equal to 0.")
    settings["request_timeout_seconds"] = positive_int(
        settings["request_timeout_seconds"],
        "request_timeout_seconds",
    )
    settings["source_sleep_seconds"] = non_negative_float(
        settings["source_sleep_seconds"],
        "source_sleep_seconds",
    )
    settings["user_agent"] = str(settings["user_agent"]).strip() or USER_AGENT
    settings["openalex_enabled"] = parse_bool(settings["openalex_enabled"], "openalex_enabled")
    settings["openalex_per_page"] = positive_int(settings["openalex_per_page"], "openalex_per_page")
    settings["openalex_mailto"] = str(settings["openalex_mailto"]).strip()
    settings["semantic_scholar_enabled"] = parse_bool(
        settings["semantic_scholar_enabled"],
        "semantic_scholar_enabled",
    )
    settings["semantic_scholar_per_page"] = positive_int(
        settings["semantic_scholar_per_page"],
        "semantic_scholar_per_page",
    )
    settings["semantic_scholar_api_key"] = str(settings["semantic_scholar_api_key"]).strip()
    settings["deepseek_summaries"] = parse_bool(
        settings["deepseek_summaries"],
        "deepseek_summaries",
    )
    settings["deepseek_base_url"] = str(settings["deepseek_base_url"]).strip()
    if not settings["deepseek_base_url"]:
        raise ValueError("deepseek_base_url cannot be empty.")
    settings["deepseek_api_key"] = str(settings["deepseek_api_key"]).strip()
    settings["deepseek_model"] = str(settings["deepseek_model"]).strip()
    if not settings["deepseek_model"]:
        raise ValueError("deepseek_model cannot be empty.")
    settings["deepseek_summary_max_tokens"] = positive_int(
        settings["deepseek_summary_max_tokens"],
        "deepseek_summary_max_tokens",
    )
    settings["deepseek_temperature"] = bounded_float(
        settings["deepseek_temperature"],
        "deepseek_temperature",
        0.0,
        2.0,
    )
    settings["deepseek_top_p"] = bounded_float(
        settings["deepseek_top_p"],
        "deepseek_top_p",
        0.0,
        1.0,
    )
    settings["deepseek_timeout_seconds"] = positive_int(
        settings["deepseek_timeout_seconds"],
        "deepseek_timeout_seconds",
    )
    settings["deepseek_sleep_seconds"] = non_negative_float(
        settings["deepseek_sleep_seconds"],
        "deepseek_sleep_seconds",
    )
    settings["deepseek_cache_enabled"] = parse_bool(
        settings["deepseek_cache_enabled"],
        "deepseek_cache_enabled",
    )
    settings["deepseek_thinking_disabled"] = parse_bool(
        settings["deepseek_thinking_disabled"],
        "deepseek_thinking_disabled",
    )
    return settings


def merge_settings_file(settings, path, required=False):
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Missing settings file: {path}")
        return settings

    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    loaded = normalize_settings_aliases(loaded)
    merged = settings.copy()
    merged.update({k: loaded[k] for k in merged if k in loaded})
    return merged


def normalize_settings_aliases(settings):
    aliases = {
        "gpt_summaries": "deepseek_summaries",
        "gpt_model": "deepseek_model",
        "gpt_summary_max_output_tokens": "deepseek_summary_max_tokens",
    }
    normalized = dict(settings)
    for old_key, new_key in aliases.items():
        if old_key in normalized and new_key not in normalized:
            normalized[new_key] = normalized[old_key]
    return normalized


def positive_int(value, name):
    value = int(value)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def non_negative_float(value, name):
    value = float(value)
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0.")
    return value


def bounded_float(value, name, minimum, maximum):
    value = float(value)
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def parse_bool(value, name):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"{name} must be a boolean.")


def load_seen():
    if not SEEN_FILE.exists():
        return {}
    return json.loads(SEEN_FILE.read_text(encoding="utf-8"))


def load_summary_cache():
    if not SUMMARY_CACHE_FILE.exists():
        if LEGACY_SUMMARY_CACHE_FILE.exists():
            return json.loads(LEGACY_SUMMARY_CACHE_FILE.read_text(encoding="utf-8"))
        return {}
    return json.loads(SUMMARY_CACHE_FILE.read_text(encoding="utf-8"))


def save_seen(seen):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_summary_cache(cache):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", value).strip()


def truncate_text(value, max_chars):
    value = clean_text(value)
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "..."


def abstract_from_inverted_index(index):
    if not isinstance(index, dict):
        return ""
    positioned_words = []
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                positioned_words.append((position, word))
    positioned_words.sort(key=lambda item: item[0])
    return clean_text(" ".join(word for _, word in positioned_words))


def normalize_title(title):
    title = clean_text(title).lower()
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def normalize_doi(doi):
    doi = (doi or "").strip().lower()
    doi = doi.removeprefix("https://doi.org/")
    doi = doi.removeprefix("http://doi.org/")
    doi = doi.removeprefix("doi:")
    return doi.strip()


def format_doi(doi):
    doi = normalize_doi(doi)
    if not doi:
        return ""
    return f"https://doi.org/{doi}"


def normalize_issn(issn):
    return re.sub(r"[^0-9X]", "", (issn or "").upper())


def split_issns(value):
    if not value:
        return []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = re.split(r"[;,|]\s*", str(value))
    return [issn for issn in (normalize_issn(v) for v in raw_values) if issn]


def append_unique(existing, new_value, separator=";"):
    values = []
    for value in str(existing or "").split(separator):
        value = value.strip()
        if value and value not in values:
            values.append(value)
    for value in str(new_value or "").split(separator):
        value = value.strip()
        if value and value not in values:
            values.append(value)
    return separator.join(values)


def parse_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", "."))
    if not match:
        return None
    return float(match.group(0))


def parse_quartile(value):
    value = str(value or "").strip().upper()
    match = re.search(r"Q?([1-4])", value)
    if not match:
        return ""
    return f"Q{match.group(1)}"


def quartile_score(quartile):
    return {
        "Q1": 1.0,
        "Q2": 0.75,
        "Q3": 0.50,
        "Q4": 0.25,
    }.get(parse_quartile(quartile), 0.0)


def impact_factor_score(impact_factor):
    if impact_factor is None:
        return None
    return min(1.0, math.log1p(max(impact_factor, 0.0)) / math.log1p(50))


def journal_metric_score(record):
    if not record:
        return 0.0
    if_score = impact_factor_score(record.get("impact_factor"))
    q_score = quartile_score(record.get("jcr_quartile"))
    if if_score is None:
        return q_score
    if q_score == 0.0:
        return if_score
    return 0.70 * if_score + 0.30 * q_score


def get_row_value(row, *names):
    for name in names:
        value = row.get(name.lower())
        if value not in (None, ""):
            return value
    return ""


def load_journal_metrics():
    metrics = {"by_issn": {}, "by_name": {}}
    if not JOURNAL_METRICS_FILE.exists():
        return metrics

    with JOURNAL_METRICS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return metrics
        for raw_row in reader:
            row = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in raw_row.items()
            }
            journal = get_row_value(row, "journal", "journal_name", "name")
            impact_factor = parse_float(
                get_row_value(row, "impact_factor", "journal_impact_factor", "jif", "if")
            )
            jcr_quartile = parse_quartile(
                get_row_value(row, "jcr_quartile", "jcr", "quartile", "jcr_partition")
            )
            issns = split_issns(
                get_row_value(row, "issn", "issn_l", "eissn", "pissn")
            )

            if not journal and not issns:
                continue

            record = {
                "journal": journal,
                "impact_factor": impact_factor,
                "jcr_quartile": jcr_quartile,
            }
            for issn in issns:
                metrics["by_issn"][issn] = record
            if journal:
                metrics["by_name"][normalize_title(journal)] = record

    return metrics


def match_journal_metric(paper, metrics):
    for issn in split_issns(paper.get("journal_issn_l")) + split_issns(paper.get("journal_issn")):
        record = metrics["by_issn"].get(issn)
        if record:
            return record, f"issn:{issn}"

    journal_name = normalize_title(paper.get("journal"))
    if journal_name:
        record = metrics["by_name"].get(journal_name)
        if record:
            return record, f"name:{paper.get('journal')}"

    return None, ""


def apply_journal_metrics(papers, metrics):
    for paper in papers:
        record, matched_by = match_journal_metric(paper, metrics)
        paper["journal_impact_factor"] = (
            record.get("impact_factor") if record and record.get("impact_factor") is not None else ""
        )
        paper["jcr_quartile"] = record.get("jcr_quartile") if record else ""
        paper["journal_metric_score"] = journal_metric_score(record)
        paper["journal_metric_match"] = matched_by
    return papers


def request_json(url, settings, headers=None):
    request_headers = {"User-Agent": settings["user_agent"]}
    request_headers.update(headers or {})
    req = Request(url, headers=request_headers)
    with urlopen(req, timeout=settings["request_timeout_seconds"]) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url, payload, settings, headers=None, timeout=None):
    request_headers = {
        "User-Agent": settings["user_agent"],
        "Content-Type": "application/json",
    }
    request_headers.update(headers or {})
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers=request_headers, method="POST")
    with urlopen(req, timeout=timeout or settings["request_timeout_seconds"]) as response:
        return json.loads(response.read().decode("utf-8"))


def openalex_search(keyword, from_date, settings):
    params = {
        "search": keyword,
        "filter": f"from_publication_date:{from_date}",
        "per-page": settings["openalex_per_page"],
        "sort": "publication_date:desc",
    }

    mailto = settings["openalex_mailto"] or os.environ.get("OPENALEX_MAILTO")
    if mailto:
        params["mailto"] = mailto

    url = "https://api.openalex.org/works?" + urlencode(params)
    data = request_json(url, settings)
    return data.get("results", [])


def semantic_scholar_search(keyword, from_date, settings):
    from_year = date.fromisoformat(from_date).year
    current_year = date.today().year
    year_range = str(current_year) if from_year == current_year else f"{from_year}-{current_year}"
    params = {
        "query": keyword,
        "limit": settings["semantic_scholar_per_page"],
        "year": year_range,
        "fields": ",".join(
            [
                "paperId",
                "title",
                "abstract",
                "year",
                "publicationDate",
                "venue",
                "journal",
                "externalIds",
                "citationCount",
                "isOpenAccess",
                "url",
            ]
        ),
    }
    headers = {}
    api_key = settings["semantic_scholar_api_key"] or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(params)
    data = request_json(url, settings, headers=headers)
    return data.get("data", [])


def extract_openalex_work(work, keyword):
    title = clean_text(work.get("display_name") or "")
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
    issns = source.get("issn") or []

    return {
        "title": title,
        "normalized_title": normalize_title(title),
        "abstract": abstract_from_inverted_index(work.get("abstract_inverted_index")),
        "doi": format_doi(work.get("doi")),
        "publication_date": work.get("publication_date") or "",
        "journal": source.get("display_name") or MISSING,
        "journal_issn": ";".join(issns),
        "journal_issn_l": source.get("issn_l") or "",
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "fwci": work.get("fwci"),
        "is_retracted": bool(work.get("is_retracted") or False),
        "is_open_access": open_access.get("is_oa"),
        "matched_keyword": keyword,
        "sources": "OpenAlex",
        "openalex_id": work.get("id") or "",
        "semantic_scholar_id": "",
        "url": work.get("id") or "",
    }


def extract_semantic_scholar_work(work, keyword):
    title = clean_text(work.get("title") or "")
    external_ids = work.get("externalIds") or {}
    journal = work.get("journal") or {}
    journal_name = journal.get("name") or work.get("venue") or MISSING
    publication_date = work.get("publicationDate") or ""
    if not publication_date and work.get("year"):
        publication_date = f"{work.get('year')}-01-01"

    return {
        "title": title,
        "normalized_title": normalize_title(title),
        "abstract": clean_text(work.get("abstract") or ""),
        "doi": format_doi(external_ids.get("DOI")),
        "publication_date": publication_date,
        "journal": journal_name,
        "journal_issn": "",
        "journal_issn_l": "",
        "cited_by_count": int(work.get("citationCount") or 0),
        "fwci": None,
        "is_retracted": False,
        "is_open_access": work.get("isOpenAccess"),
        "matched_keyword": keyword,
        "sources": "Semantic Scholar",
        "openalex_id": "",
        "semantic_scholar_id": work.get("paperId") or "",
        "url": work.get("url") or "",
    }


def is_recent_enough(publication_date, from_date):
    if not publication_date:
        return True
    try:
        return date.fromisoformat(publication_date) >= date.fromisoformat(from_date)
    except ValueError:
        return True


def paper_key(paper):
    doi = normalize_doi(paper.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = paper.get("normalized_title") or normalize_title(paper.get("title"))
    if title:
        return f"title:{title}"
    return ""


def seen_keys_for(paper):
    doi = normalize_doi(paper.get("doi"))
    title = paper.get("normalized_title") or normalize_title(paper.get("title"))
    keys = [paper_key(paper), paper.get("doi", ""), doi, title]
    return {key for key in keys if key}


def is_seen(paper, seen):
    return any(key in seen for key in seen_keys_for(paper))


def merge_paper(existing, new_paper):
    existing["sources"] = append_unique(existing.get("sources"), new_paper.get("sources"))
    existing["matched_keyword"] = append_unique(
        existing.get("matched_keyword"), new_paper.get("matched_keyword")
    )
    existing["journal_issn"] = append_unique(
        existing.get("journal_issn"), new_paper.get("journal_issn")
    )

    if new_paper.get("cited_by_count", 0) > existing.get("cited_by_count", 0):
        existing["cited_by_count"] = new_paper["cited_by_count"]

    if new_paper.get("is_open_access"):
        existing["is_open_access"] = True

    for field in [
        "doi",
        "abstract",
        "publication_date",
        "journal",
        "journal_issn_l",
        "fwci",
        "openalex_id",
        "semantic_scholar_id",
        "url",
    ]:
        if existing.get(field) in ("", None, MISSING) and new_paper.get(field) not in ("", None):
            existing[field] = new_paper[field]

    return existing


def dedupe(papers):
    deduped = {}
    for paper in papers:
        key = paper_key(paper)
        if not key:
            continue
        if key in deduped:
            merge_paper(deduped[key], paper)
        else:
            deduped[key] = paper
    return list(deduped.values())


def relevance_score(title, keyword):
    title_norm = normalize_title(title)
    keywords = [k.strip() for k in str(keyword or "").split(";") if k.strip()]
    if not keywords:
        return 0.0

    best_score = 0.0
    for item in keywords:
        item_norm = normalize_title(item)
        terms = [t for t in item_norm.split() if len(t) > 2]
        if not terms:
            continue
        hits = sum(1 for term in terms if term in title_norm)
        phrase_hit = 1 if item_norm in title_norm else 0
        best_score = max(best_score, min(1.0, (hits / len(terms)) * 0.75 + phrase_hit * 0.25))
    return best_score


def recency_score(publication_date, days):
    try:
        published = date.fromisoformat(publication_date)
    except Exception:
        return 0.0
    age = (date.today() - published).days
    if age < 0:
        return 0.0
    return max(0.0, 1.0 - age / max(days, 1))


def score_paper(paper, days):
    rel = relevance_score(paper["title"], paper["matched_keyword"])
    citation = min(1.0, math.log1p(paper["cited_by_count"]) / math.log1p(500))
    recency = recency_score(paper["publication_date"], days)
    oa = 1.0 if paper["is_open_access"] else 0.0
    journal_metric = float(paper.get("journal_metric_score") or 0.0)

    return (
        0.40 * rel
        + 0.25 * citation
        + 0.20 * recency
        + 0.10 * journal_metric
        + 0.05 * oa
    )


def display_metric(value):
    if value in ("", None):
        return MISSING
    if isinstance(value, float):
        return f"{value:.3g}"
    return value


def deepseek_chat_completions_url(settings):
    return settings["deepseek_base_url"].rstrip("/") + "/chat/completions"


def build_deepseek_summary_prompt(paper):
    abstract = truncate_text(paper.get("abstract") or "", 3500) or MISSING
    return "\n".join(
        [
            "请用中文总结下面这篇学术论文。只能依据给定元数据和摘要，不要猜测不存在的信息。",
            "输出 4 条 Markdown bullet，格式固定为：",
            "- 内容概述：...",
            "- 创新点：...",
            "- 研究价值：...",
            "- 注意事项：...",
            "",
            f"标题：{paper.get('title') or MISSING}",
            f"DOI：{paper.get('doi') or MISSING}",
            f"期刊/来源：{paper.get('journal') or MISSING}",
            f"发表日期：{paper.get('publication_date') or MISSING}",
            f"引用数：{paper.get('cited_by_count', 0)}",
            f"FWCI：{display_metric(paper.get('fwci'))}",
            f"影响因子：{display_metric(paper.get('journal_impact_factor'))}",
            f"JCR 分区：{paper.get('jcr_quartile') or MISSING}",
            f"匹配关键词：{paper.get('matched_keyword') or MISSING}",
            f"摘要：{abstract}",
        ]
    )


def extract_chat_completion_text(data):
    choices = data.get("choices") or []
    text_parts = []
    for choice in choices:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            text_parts.append(content.strip())
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("text"):
                    text_parts.append(str(item["text"]).strip())
    return "\n".join(part for part in text_parts if part).strip()


def call_deepseek_summary(paper, settings, api_key):
    payload = {
        "model": settings["deepseek_model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是严谨的中文学术论文雷达助手。总结要具体、克制，"
                    "突出论文内容、创新点和研究价值；摘要不足时必须说明信息有限。"
                ),
            },
            {
                "role": "user",
                "content": build_deepseek_summary_prompt(paper),
            },
        ],
        "max_tokens": settings["deepseek_summary_max_tokens"],
        "temperature": settings["deepseek_temperature"],
        "top_p": settings["deepseek_top_p"],
        "stream": False,
    }
    if settings["deepseek_thinking_disabled"]:
        payload["thinking"] = {"type": "disabled"}
    headers = {"Authorization": f"Bearer {api_key}"}
    data = post_json(
        deepseek_chat_completions_url(settings),
        payload,
        settings,
        headers=headers,
        timeout=settings["deepseek_timeout_seconds"],
    )
    summary = extract_chat_completion_text(data)
    if not summary:
        raise ValueError("DeepSeek response did not contain summary text.")
    return summary


def enrich_deepseek_summaries(papers, settings):
    if not settings["deepseek_summaries"]:
        for paper in papers:
            paper["deepseek_summary"] = ""
        return

    api_key = settings["deepseek_api_key"] or os.environ.get("DEEPSEEK_API_KEY")
    model = settings["deepseek_model"]
    cache = load_summary_cache() if settings["deepseek_cache_enabled"] else {}

    if not api_key:
        for paper in papers:
            paper["deepseek_summary"] = "未生成（缺少 DEEPSEEK_API_KEY，无法调用 DeepSeek）。"
        return

    for index, paper in enumerate(papers, start=1):
        key = paper_key(paper)
        cached = cache.get(key)
        if settings["deepseek_cache_enabled"] and cached and cached.get("model") == model and cached.get("summary"):
            paper["deepseek_summary"] = cached["summary"]
            continue

        print(f"Summarizing with DeepSeek ({index}/{len(papers)}): {paper['title']}")
        try:
            summary = call_deepseek_summary(paper, settings, api_key)
            paper["deepseek_summary"] = summary
            cache[key] = {
                "title": paper["title"],
                "doi": paper.get("doi", ""),
                "model": model,
                "summary": summary,
                "updated_at": date.today().isoformat(),
            }
            if settings["deepseek_cache_enabled"]:
                save_summary_cache(cache)
            time.sleep(settings["deepseek_sleep_seconds"])
        except Exception as exc:
            paper["deepseek_summary"] = f"未生成（DeepSeek 调用失败：{format_error(exc)}）。"


def append_indented_markdown(lines, text, indent="   "):
    for line in str(text or "").splitlines():
        lines.append(f"{indent}{line}" if line.strip() else "")


def build_full_markdown(papers):
    lines = ["# Paper Radar Latest Results", ""]
    for i, paper in enumerate(papers, start=1):
        lines.append(f"## {i}. {paper['title']}")
        lines.append("")
        lines.append(f"- DOI: {paper.get('doi') or MISSING}")
        lines.append(f"- Journal: {paper.get('journal') or MISSING}")
        lines.append(f"- Impact factor: {display_metric(paper.get('journal_impact_factor'))}")
        lines.append(f"- JCR quartile: {paper.get('jcr_quartile') or MISSING}")
        lines.append(f"- Date: {paper.get('publication_date') or MISSING}")
        lines.append(f"- Citations: {paper.get('cited_by_count', 0)}")
        lines.append(f"- FWCI: {display_metric(paper.get('fwci'))}")
        lines.append(f"- Sources: {paper.get('sources') or MISSING}")
        lines.append(f"- Matched keyword: {paper.get('matched_keyword')}")
        lines.append(f"- Score: {paper.get('score'):.4f}")
        lines.append("")
    return "\n".join(lines)


def build_title_only_markdown(papers):
    lines = ["# Paper Radar Latest Titles", ""]
    for i, paper in enumerate(papers, start=1):
        lines.append(f"{i}. {paper['title']}")
        if paper.get("doi"):
            lines.append(f"   DOI: {paper['doi']}")
        if paper.get("deepseek_summary"):
            lines.append("   DeepSeek 总结：")
            append_indented_markdown(lines, paper["deepseek_summary"], indent="   ")
        lines.append("")
    return "\n".join(lines)


def write_outputs(papers, title_only=False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fields = [
        "score",
        "title",
        "abstract",
        "doi",
        "publication_date",
        "journal",
        "journal_issn",
        "journal_issn_l",
        "journal_impact_factor",
        "jcr_quartile",
        "journal_metric_score",
        "journal_metric_match",
        "cited_by_count",
        "fwci",
        "is_open_access",
        "matched_keyword",
        "sources",
        "openalex_id",
        "semantic_scholar_id",
        "url",
        "deepseek_summary",
    ]

    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            writer.writerow({field: paper.get(field, "") for field in fields})

    full_markdown = build_full_markdown(papers)
    title_only_markdown = build_title_only_markdown(papers)
    MD_OUTPUT.write_text(
        title_only_markdown if title_only else full_markdown,
        encoding="utf-8-sig",
    )
    TITLE_ONLY_OUTPUT.write_text(title_only_markdown, encoding="utf-8-sig")


def fetch_keyword_papers(keyword, from_date, settings, use_semantic_scholar=True):
    papers = []
    semantic_scholar_limited = False

    if settings["openalex_enabled"]:
        print(f"Searching OpenAlex: {keyword}")
        try:
            for work in openalex_search(keyword, from_date, settings):
                paper = extract_openalex_work(work, keyword)
                if paper["is_retracted"] or not paper["title"]:
                    continue
                papers.append(paper)
        except Exception as exc:
            print(f"Warning: OpenAlex failed for keyword '{keyword}': {format_error(exc)}")

        time.sleep(settings["source_sleep_seconds"])

    if not settings["semantic_scholar_enabled"] or not use_semantic_scholar:
        return papers, semantic_scholar_limited

    print(f"Searching Semantic Scholar: {keyword}")
    try:
        for work in semantic_scholar_search(keyword, from_date, settings):
            paper = extract_semantic_scholar_work(work, keyword)
            if not paper["title"] or not is_recent_enough(paper["publication_date"], from_date):
                continue
            papers.append(paper)
    except Exception as exc:
        print(f"Warning: Semantic Scholar failed for keyword '{keyword}': {format_error(exc)}")
        semantic_scholar_limited = is_rate_limited(exc)

    time.sleep(settings["source_sleep_seconds"])
    return papers, semantic_scholar_limited


def format_error(exc):
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    return str(exc)


def is_rate_limited(exc):
    return isinstance(exc, HTTPError) and exc.code == 429


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument("--title-only", dest="title_only", action="store_true", default=None)
    parser.add_argument("--no-title-only", dest="title_only", action="store_false")
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--deepseek-summary", dest="deepseek_summaries", action="store_true", default=None)
    parser.add_argument("--no-deepseek-summary", dest="deepseek_summaries", action="store_false")
    parser.add_argument("--deepseek-base-url", default=None)
    parser.add_argument("--deepseek-api-key", default=None)
    parser.add_argument("--deepseek-model", default=None)
    parser.add_argument("--deepseek-max-tokens", type=int, default=None)
    parser.add_argument("--deepseek-temperature", type=float, default=None)
    parser.add_argument("--deepseek-top-p", type=float, default=None)
    parser.add_argument("--gpt-summary", dest="deepseek_summaries", action="store_true")
    parser.add_argument("--no-gpt-summary", dest="deepseek_summaries", action="store_false")
    parser.add_argument("--gpt-model", dest="deepseek_model", default=None)
    parser.add_argument("--include-seen", dest="include_seen", action="store_true", default=None)
    parser.add_argument("--no-include-seen", dest="include_seen", action="store_false")
    parser.set_defaults(deepseek_summaries=None)
    return parser.parse_args()


def main():
    args = parse_args()
    settings = load_settings()
    if args.days is not None:
        settings["days"] = positive_int(args.days, "days")
    if args.top is not None:
        settings["top"] = positive_int(args.top, "top")
    if args.title_only is not None:
        settings["title_only"] = args.title_only
    if args.min_score is not None:
        settings["min_score"] = float(args.min_score)
    if args.include_seen is not None:
        settings["include_seen"] = args.include_seen
    if args.deepseek_summaries is not None:
        settings["deepseek_summaries"] = args.deepseek_summaries
    if args.deepseek_base_url is not None:
        settings["deepseek_base_url"] = args.deepseek_base_url.strip()
    if args.deepseek_api_key is not None:
        settings["deepseek_api_key"] = args.deepseek_api_key.strip()
    if args.deepseek_model is not None:
        settings["deepseek_model"] = args.deepseek_model.strip()
    if args.deepseek_max_tokens is not None:
        settings["deepseek_summary_max_tokens"] = positive_int(
            args.deepseek_max_tokens,
            "deepseek_summary_max_tokens",
        )
    if args.deepseek_temperature is not None:
        settings["deepseek_temperature"] = bounded_float(
            args.deepseek_temperature,
            "deepseek_temperature",
            0.0,
            2.0,
        )
    if args.deepseek_top_p is not None:
        settings["deepseek_top_p"] = bounded_float(
            args.deepseek_top_p,
            "deepseek_top_p",
            0.0,
            1.0,
        )
    if settings["min_score"] < 0:
        raise ValueError("min_score must be greater than or equal to 0.")
    if not settings["deepseek_base_url"]:
        raise ValueError("deepseek_base_url cannot be empty.")
    if not settings["deepseek_model"]:
        raise ValueError("deepseek_model cannot be empty.")

    keywords = read_keywords()
    from_date = (date.today() - timedelta(days=settings["days"])).isoformat()
    metrics = load_journal_metrics()

    all_papers = []
    use_semantic_scholar = True
    for keyword in keywords:
        keyword_papers, semantic_scholar_limited = fetch_keyword_papers(
            keyword,
            from_date,
            settings,
            use_semantic_scholar=use_semantic_scholar,
        )
        all_papers.extend(keyword_papers)
        if semantic_scholar_limited:
            use_semantic_scholar = False
            print("Warning: Semantic Scholar rate limit reached; skipping it for remaining keywords.")

    papers = dedupe(all_papers)
    apply_journal_metrics(papers, metrics)
    seen = load_seen()

    if not settings["include_seen"]:
        papers = [paper for paper in papers if not is_seen(paper, seen)]

    for paper in papers:
        paper["score"] = score_paper(paper, settings["days"])

    papers = [paper for paper in papers if paper["score"] >= settings["min_score"]]
    papers.sort(key=lambda p: p["score"], reverse=True)
    papers = papers[: settings["top"]]

    enrich_deepseek_summaries(papers, settings)
    write_outputs(papers, title_only=settings["title_only"])

    for paper in papers:
        key = paper_key(paper)
        seen[key] = {
            "title": paper["title"],
            "doi": paper["doi"],
            "first_seen": date.today().isoformat(),
        }
    save_seen(seen)

    print(f"Done. Wrote: {CSV_OUTPUT}")
    print(f"Done. Wrote: {MD_OUTPUT}")
    print(f"Done. Wrote: {TITLE_ONLY_OUTPUT}")


if __name__ == "__main__":
    main()
