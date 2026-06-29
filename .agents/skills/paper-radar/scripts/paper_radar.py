import argparse
import csv
import html
import json
import math
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"

KEYWORDS_FILE = CONFIG_DIR / "keywords.txt"
TOPICS_FILE = CONFIG_DIR / "topics.yaml"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LOCAL_SETTINGS_FILE = CONFIG_DIR / "settings.local.json"
JOURNAL_METRICS_FILE = CONFIG_DIR / "journal_metrics.csv"
SEEN_FILE = DATA_DIR / "seen_papers.json"
SUMMARY_CACHE_FILE = DATA_DIR / "deepseek_summaries.json"
LEGACY_SUMMARY_CACHE_FILE = DATA_DIR / "gpt_summaries.json"
CSV_OUTPUT = OUTPUT_DIR / "ranked_papers.csv"
MD_OUTPUT = OUTPUT_DIR / "latest_titles.md"
TITLE_ONLY_OUTPUT = OUTPUT_DIR / "latest_titles_title_only.md"
ZOTERO_REVIEW_OUTPUT = OUTPUT_DIR / "zotero_review_queue.csv"
ZOTERO_BIB_OUTPUT = OUTPUT_DIR / "zotero_import.bib"
OBSIDIAN_OUTPUT_DIR = OUTPUT_DIR / "obsidian"

USER_AGENT = "paper-radar/1.0"
DEFAULT_SETTINGS = {
    "days": 30,
    "top": 30,
    "title_only": False,
    "min_score": 0.0,
    "min_relevance": 0.25,
    "include_seen": False,
    "request_timeout_seconds": 30,
    "source_sleep_seconds": 0.5,
    "user_agent": USER_AGENT,
    "openalex_enabled": True,
    "openalex_per_page": 50,
    "openalex_mailto": "",
    "excluded_work_types": ["dataset"],
    "excluded_title_patterns": ["data and code for"],
    "semantic_scholar_enabled": True,
    "semantic_scholar_per_page": 50,
    "semantic_scholar_api_key": "",
    "arxiv_enabled": True,
    "arxiv_max_results": 50,
    "arxiv_sort_by": "submittedDate",
    "arxiv_sort_order": "descending",
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
    "deepseek_json_output": True,
    "max_keywords_per_paper": 8,
    "relevance_title_weight": 0.75,
    "relevance_abstract_weight": 0.25,
    "score_weight_relevance": 0.65,
    "score_weight_citation": 0.15,
    "score_weight_recency": 0.10,
    "score_weight_journal": 0.07,
    "score_weight_open_access": 0.03,
    "zotero_export_enabled": True,
    "zotero_tag_prefix": "paper-radar",
    "obsidian_export_enabled": True,
    "obsidian_vault_path": "",
    "obsidian_inbox_folder": "00_Inbox",
    "obsidian_literature_folder": "01_Literature_Notes",
    "obsidian_topic_folder": "03_Topic_Index",
    "obsidian_note_status": "to-read",
    "obsidian_overwrite_notes": False,
    "obsidian_topic_index_enabled": True,
    "log_file": "outputs/run_log.txt",
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


def read_search_topics():
    if TOPICS_FILE.exists():
        topics = read_topics_yaml(TOPICS_FILE)
        if topics:
            return topics

    return [
        {
            "topic_id": "default",
            "name_zh": "默认主题",
            "name_en": "Default",
            "keywords": read_keywords(),
            "exclude_keywords": [],
            "tags": [],
            "obsidian_subdir": "",
        }
    ]


def read_topics_yaml(path):
    parsed = parse_simple_topics_yaml(path.read_text(encoding="utf-8-sig"))
    topics_data = parsed.get("topics") or {}
    topics = []
    for topic_id, topic in topics_data.items():
        keywords = topic.get("keywords") or []
        if not keywords:
            continue
        topics.append(
            {
                "topic_id": str(topic_id),
                "name_zh": str(topic.get("name_zh") or topic_id),
                "name_en": str(topic.get("name_en") or topic_id),
                "keywords": [str(item) for item in keywords],
                "exclude_keywords": [str(item) for item in topic.get("exclude_keywords", [])],
                "tags": [str(item) for item in topic.get("tags", [])],
                "obsidian_subdir": str(topic.get("obsidian_subdir") or topic_id),
            }
        )
    if not topics:
        raise ValueError("config/topics.yaml exists but contains no topics with keywords.")
    return topics


def parse_simple_topics_yaml(text):
    data = {}
    current_topic = None
    current_list = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if indent == 0 and line == "topics:":
            data["topics"] = {}
            current_topic = None
            current_list = None
            continue

        if indent == 2 and line.endswith(":"):
            current_topic = line[:-1].strip()
            data.setdefault("topics", {})[current_topic] = {}
            current_list = None
            continue

        if current_topic is None:
            continue

        topic = data["topics"][current_topic]
        if indent == 4 and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = parse_yaml_scalar(value.strip())
            if value == "":
                topic[key] = []
                current_list = key
            else:
                topic[key] = value
                current_list = None
            continue

        if indent >= 6 and line.startswith("- ") and current_list:
            topic.setdefault(current_list, []).append(parse_yaml_scalar(line[2:].strip()))

    return data


def parse_yaml_scalar(value):
    value = value.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


class RunLogger:
    def __init__(self):
        self.lines = []

    def add(self, message):
        timestamp = datetime.now().isoformat(timespec="seconds")
        self.lines.append(f"[{timestamp}] {message}")

    def print(self, message):
        print(message)
        self.add(message)

    def write(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(self.lines) + "\n", encoding="utf-8-sig")


def resolve_output_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    return path


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
    settings["min_relevance"] = bounded_float(
        settings["min_relevance"],
        "min_relevance",
        0.0,
        1.0,
    )
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
    settings["excluded_work_types"] = string_list(settings["excluded_work_types"], "excluded_work_types")
    settings["excluded_title_patterns"] = string_list(
        settings["excluded_title_patterns"],
        "excluded_title_patterns",
    )
    settings["semantic_scholar_enabled"] = parse_bool(
        settings["semantic_scholar_enabled"],
        "semantic_scholar_enabled",
    )
    settings["semantic_scholar_per_page"] = positive_int(
        settings["semantic_scholar_per_page"],
        "semantic_scholar_per_page",
    )
    settings["semantic_scholar_api_key"] = str(settings["semantic_scholar_api_key"]).strip()
    settings["arxiv_enabled"] = parse_bool(settings["arxiv_enabled"], "arxiv_enabled")
    settings["arxiv_max_results"] = positive_int(settings["arxiv_max_results"], "arxiv_max_results")
    settings["arxiv_sort_by"] = str(settings["arxiv_sort_by"]).strip() or "submittedDate"
    settings["arxiv_sort_order"] = str(settings["arxiv_sort_order"]).strip() or "descending"
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
    settings["deepseek_json_output"] = parse_bool(
        settings["deepseek_json_output"],
        "deepseek_json_output",
    )
    settings["max_keywords_per_paper"] = positive_int(
        settings["max_keywords_per_paper"],
        "max_keywords_per_paper",
    )
    settings["relevance_title_weight"] = non_negative_float(
        settings["relevance_title_weight"],
        "relevance_title_weight",
    )
    settings["relevance_abstract_weight"] = non_negative_float(
        settings["relevance_abstract_weight"],
        "relevance_abstract_weight",
    )
    relevance_weight_total = settings["relevance_title_weight"] + settings["relevance_abstract_weight"]
    if relevance_weight_total <= 0:
        raise ValueError("relevance title/abstract weights must sum to a positive number.")
    settings["score_weight_relevance"] = non_negative_float(
        settings["score_weight_relevance"],
        "score_weight_relevance",
    )
    settings["score_weight_citation"] = non_negative_float(
        settings["score_weight_citation"],
        "score_weight_citation",
    )
    settings["score_weight_recency"] = non_negative_float(
        settings["score_weight_recency"],
        "score_weight_recency",
    )
    settings["score_weight_journal"] = non_negative_float(
        settings["score_weight_journal"],
        "score_weight_journal",
    )
    settings["score_weight_open_access"] = non_negative_float(
        settings["score_weight_open_access"],
        "score_weight_open_access",
    )
    score_weight_total = (
        settings["score_weight_relevance"]
        + settings["score_weight_citation"]
        + settings["score_weight_recency"]
        + settings["score_weight_journal"]
        + settings["score_weight_open_access"]
    )
    if score_weight_total <= 0:
        raise ValueError("score weights must sum to a positive number.")
    settings["zotero_export_enabled"] = parse_bool(
        settings["zotero_export_enabled"],
        "zotero_export_enabled",
    )
    settings["zotero_tag_prefix"] = str(settings["zotero_tag_prefix"]).strip()
    settings["obsidian_export_enabled"] = parse_bool(
        settings["obsidian_export_enabled"],
        "obsidian_export_enabled",
    )
    settings["obsidian_vault_path"] = str(settings["obsidian_vault_path"]).strip()
    settings["obsidian_inbox_folder"] = str(settings["obsidian_inbox_folder"]).strip() or "00_Inbox"
    settings["obsidian_literature_folder"] = (
        str(settings["obsidian_literature_folder"]).strip() or "01_Literature_Notes"
    )
    settings["obsidian_topic_folder"] = str(settings["obsidian_topic_folder"]).strip() or "03_Topic_Index"
    settings["obsidian_note_status"] = str(settings["obsidian_note_status"]).strip() or "to-read"
    settings["obsidian_overwrite_notes"] = parse_bool(
        settings["obsidian_overwrite_notes"],
        "obsidian_overwrite_notes",
    )
    settings["obsidian_topic_index_enabled"] = parse_bool(
        settings["obsidian_topic_index_enabled"],
        "obsidian_topic_index_enabled",
    )
    settings["log_file"] = str(settings["log_file"]).strip() or "outputs/run_log.txt"
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


def string_list(value, name):
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    raise ValueError(f"{name} must be a list of strings or a comma-separated string.")


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


def as_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[;,|]\s*", str(value)) if item.strip()]


def append_unique_list(existing, new_value):
    values = []
    for item in as_list(existing) + as_list(new_value):
        if item and item not in values:
            values.append(item)
    return values


def csv_value(value):
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if value is None:
        return ""
    return value


def first_nonempty(*values):
    for value in values:
        if value not in ("", None, MISSING, []):
            return value
    return ""


def year_from_date(publication_date, fallback=""):
    if publication_date:
        match = re.match(r"(\d{4})", str(publication_date))
        if match:
            return int(match.group(1))
    if fallback not in ("", None):
        try:
            return int(fallback)
        except (TypeError, ValueError):
            return ""
    return ""


def date_part(value):
    value = str(value or "").strip()
    if not value:
        return ""
    match = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if match:
        return match.group(1)
    match = re.match(r"(\d{4})$", value)
    if match:
        return f"{match.group(1)}-01-01"
    return value


def normalize_arxiv_id(value):
    value = str(value or "").strip()
    if not value:
        return ""
    value = value.removeprefix("https://arxiv.org/abs/")
    value = value.removeprefix("http://arxiv.org/abs/")
    value = value.removeprefix("arXiv:")
    value = value.removeprefix("arxiv:")
    return re.sub(r"v\d+$", "", value)


def arxiv_id_from_doi(doi):
    match = re.search(r"10\.48550/arxiv\.([^/]+)$", normalize_doi(doi), flags=re.IGNORECASE)
    if not match:
        return ""
    return normalize_arxiv_id(match.group(1))


def paper_url_from_ids(paper):
    return first_nonempty(
        paper.get("url"),
        paper.get("doi"),
        f"https://arxiv.org/abs/{paper['arxiv_id']}" if paper.get("arxiv_id") else "",
        paper.get("openalex_id"),
    )


def complete_paper(paper, keyword, topic, source_name):
    paper["title"] = clean_text(paper.get("title") or "")
    paper["normalized_title"] = paper.get("normalized_title") or normalize_title(paper["title"])
    paper["abstract"] = clean_text(paper.get("abstract") or "")
    paper["authors"] = as_list(paper.get("authors"))
    paper["publication_date"] = date_part(paper.get("publication_date"))
    paper["updated_date"] = date_part(paper.get("updated_date"))
    paper["year"] = year_from_date(paper.get("publication_date"), paper.get("year"))
    paper["doi"] = format_doi(paper.get("doi"))
    paper["arxiv_id"] = normalize_arxiv_id(paper.get("arxiv_id"))
    if not paper["arxiv_id"]:
        paper["arxiv_id"] = arxiv_id_from_doi(paper.get("doi"))
    paper["semantic_scholar_id"] = str(paper.get("semantic_scholar_id") or "")
    paper["openalex_id"] = str(paper.get("openalex_id") or "")
    paper["journal"] = first_nonempty(paper.get("journal"), paper.get("venue")) or MISSING
    paper["venue"] = first_nonempty(paper.get("venue"), paper.get("journal")) or MISSING
    paper["source"] = paper.get("source") or source_name
    paper["sources"] = paper.get("sources") or source_name
    paper["citation_count"] = int(paper.get("citation_count", paper.get("cited_by_count", 0)) or 0)
    paper["cited_by_count"] = paper["citation_count"]
    paper["is_open_access"] = bool(paper.get("is_open_access") or False)
    paper["keyword"] = keyword
    paper["matched_keyword"] = append_unique(paper.get("matched_keyword"), keyword)
    paper["matched_keywords"] = append_unique_list(paper.get("matched_keywords"), [keyword])
    paper["url"] = paper_url_from_ids(paper)
    paper.setdefault("pdf_url", "")
    paper.setdefault("work_type", "paper")
    paper.setdefault("fwci", None)
    paper.setdefault("is_retracted", False)
    paper.setdefault("journal_issn", "")
    paper.setdefault("journal_issn_l", "")
    paper.setdefault("summary", "")
    paper.setdefault("summary_zh", "")
    paper.setdefault("deepseek_summary", "")
    paper.setdefault("summary_structured", {})
    paper.setdefault("extracted_keywords", [])
    paper.setdefault("reading_priority", "")
    paper.setdefault("why_relevant", "")

    if topic:
        paper["topic_id"] = topic.get("topic_id", "default")
        paper["topic_name_zh"] = topic.get("name_zh") or topic.get("topic_id", "default")
        paper["topic_name_en"] = topic.get("name_en") or topic.get("topic_id", "default")
        paper["topic_tags"] = as_list(topic.get("tags"))
        paper["obsidian_subdir"] = topic.get("obsidian_subdir") or topic.get("topic_id", "default")
    else:
        paper.setdefault("topic_id", "default")
        paper.setdefault("topic_name_zh", "默认主题")
        paper.setdefault("topic_name_en", "Default")
        paper.setdefault("topic_tags", [])
        paper.setdefault("obsidian_subdir", "")

    return paper


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
                "authors",
                "externalIds",
                "citationCount",
                "isOpenAccess",
                "openAccessPdf",
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


def arxiv_search(keyword, settings):
    params = {
        "search_query": f'all:"{keyword}"',
        "start": 0,
        "max_results": settings["arxiv_max_results"],
        "sortBy": settings["arxiv_sort_by"],
        "sortOrder": settings["arxiv_sort_order"],
    }
    url = "https://export.arxiv.org/api/query?" + urlencode(params)
    request_headers = {"User-Agent": settings["user_agent"]}
    req = Request(url, headers=request_headers)
    with urlopen(req, timeout=settings["request_timeout_seconds"]) as response:
        root = ET.fromstring(response.read())
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    return root.findall("atom:entry", ns)


def extract_openalex_work(work, keyword):
    title = clean_text(work.get("display_name") or "")
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    open_access = work.get("open_access") or {}
    issns = source.get("issn") or []
    authors = [
        (((authorship or {}).get("author") or {}).get("display_name") or "").strip()
        for authorship in work.get("authorships") or []
    ]
    ids = work.get("ids") or {}

    return {
        "title": title,
        "normalized_title": normalize_title(title),
        "authors": [author for author in authors if author],
        "abstract": abstract_from_inverted_index(work.get("abstract_inverted_index")),
        "work_type": work.get("type") or "",
        "doi": format_doi(work.get("doi")),
        "publication_date": work.get("publication_date") or "",
        "updated_date": work.get("updated_date") or "",
        "year": work.get("publication_year") or "",
        "journal": source.get("display_name") or MISSING,
        "venue": source.get("display_name") or MISSING,
        "journal_issn": ";".join(issns),
        "journal_issn_l": source.get("issn_l") or "",
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "citation_count": int(work.get("cited_by_count") or 0),
        "fwci": work.get("fwci"),
        "is_retracted": bool(work.get("is_retracted") or False),
        "is_open_access": open_access.get("is_oa"),
        "matched_keyword": keyword,
        "matched_keywords": [keyword],
        "keyword": keyword,
        "source": "OpenAlex",
        "sources": "OpenAlex",
        "openalex_id": work.get("id") or "",
        "semantic_scholar_id": "",
        "arxiv_id": normalize_arxiv_id(ids.get("arxiv") or ""),
        "url": primary_location.get("landing_page_url") or work.get("id") or "",
        "pdf_url": primary_location.get("pdf_url") or open_access.get("oa_url") or "",
    }


def extract_semantic_scholar_work(work, keyword):
    title = clean_text(work.get("title") or "")
    external_ids = work.get("externalIds") or {}
    journal = work.get("journal") or {}
    journal_name = journal.get("name") or work.get("venue") or MISSING
    publication_date = work.get("publicationDate") or ""
    if not publication_date and work.get("year"):
        publication_date = f"{work.get('year')}-01-01"
    open_access_pdf = work.get("openAccessPdf") or {}

    return {
        "title": title,
        "normalized_title": normalize_title(title),
        "authors": [author.get("name", "") for author in work.get("authors") or [] if author.get("name")],
        "abstract": clean_text(work.get("abstract") or ""),
        "work_type": "paper",
        "doi": format_doi(external_ids.get("DOI")),
        "publication_date": publication_date,
        "updated_date": "",
        "year": work.get("year") or year_from_date(publication_date),
        "journal": journal_name,
        "venue": work.get("venue") or journal_name,
        "journal_issn": "",
        "journal_issn_l": "",
        "cited_by_count": int(work.get("citationCount") or 0),
        "citation_count": int(work.get("citationCount") or 0),
        "fwci": None,
        "is_retracted": False,
        "is_open_access": work.get("isOpenAccess"),
        "matched_keyword": keyword,
        "matched_keywords": [keyword],
        "keyword": keyword,
        "source": "Semantic Scholar",
        "sources": "Semantic Scholar",
        "openalex_id": "",
        "semantic_scholar_id": work.get("paperId") or "",
        "arxiv_id": normalize_arxiv_id(external_ids.get("ArXiv") or ""),
        "url": work.get("url") or "",
        "pdf_url": open_access_pdf.get("url") or "",
    }


def extract_arxiv_entry(entry, keyword):
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    def text(path):
        node = entry.find(path, ns)
        return clean_text(node.text if node is not None else "")

    arxiv_url = text("atom:id")
    arxiv_id = normalize_arxiv_id(arxiv_url)
    pdf_url = ""
    page_url = arxiv_url
    for link in entry.findall("atom:link", ns):
        href = link.attrib.get("href", "")
        rel = link.attrib.get("rel", "")
        link_type = link.attrib.get("type", "")
        title = link.attrib.get("title", "")
        if rel == "alternate" and href:
            page_url = href
        if link_type == "application/pdf" or title == "pdf":
            pdf_url = href

    journal_ref = text("arxiv:journal_ref")
    publication_date = date_part(text("atom:published"))
    return {
        "title": text("atom:title"),
        "normalized_title": normalize_title(text("atom:title")),
        "authors": [
            clean_text(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ],
        "abstract": text("atom:summary"),
        "work_type": "preprint",
        "doi": format_doi(text("arxiv:doi")),
        "publication_date": publication_date,
        "updated_date": date_part(text("atom:updated")),
        "year": year_from_date(publication_date),
        "journal": journal_ref or "arXiv",
        "venue": journal_ref or "arXiv",
        "journal_issn": "",
        "journal_issn_l": "",
        "cited_by_count": 0,
        "citation_count": 0,
        "fwci": None,
        "is_retracted": False,
        "is_open_access": True,
        "matched_keyword": keyword,
        "matched_keywords": [keyword],
        "keyword": keyword,
        "source": "arXiv",
        "sources": "arXiv",
        "openalex_id": "",
        "semantic_scholar_id": "",
        "arxiv_id": arxiv_id,
        "url": page_url,
        "pdf_url": pdf_url,
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
    arxiv_id = normalize_arxiv_id(paper.get("arxiv_id"))
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    semantic_scholar_id = str(paper.get("semantic_scholar_id") or "").strip()
    if semantic_scholar_id:
        return f"semantic_scholar:{semantic_scholar_id}"
    openalex_id = str(paper.get("openalex_id") or "").strip()
    if openalex_id:
        return f"openalex:{openalex_id}"
    title = paper.get("normalized_title") or normalize_title(paper.get("title"))
    if title:
        return f"title:{title}"
    return ""


def paper_keys(paper):
    doi = normalize_doi(paper.get("doi"))
    arxiv_id = normalize_arxiv_id(paper.get("arxiv_id"))
    semantic_scholar_id = str(paper.get("semantic_scholar_id") or "").strip()
    openalex_id = str(paper.get("openalex_id") or "").strip()
    title = paper.get("normalized_title") or normalize_title(paper.get("title"))
    keys = []
    if doi:
        keys.append(f"doi:{doi}")
    if arxiv_id:
        keys.append(f"arxiv:{arxiv_id}")
    if semantic_scholar_id:
        keys.append(f"semantic_scholar:{semantic_scholar_id}")
    if openalex_id:
        keys.append(f"openalex:{openalex_id}")
    if title:
        keys.append(f"title:{title}")
    return keys


def seen_keys_for(paper):
    doi = normalize_doi(paper.get("doi"))
    arxiv_id = normalize_arxiv_id(paper.get("arxiv_id"))
    title = paper.get("normalized_title") or normalize_title(paper.get("title"))
    keys = paper_keys(paper) + [
        paper.get("doi", ""),
        doi,
        arxiv_id,
        paper.get("semantic_scholar_id", ""),
        paper.get("openalex_id", ""),
        title,
    ]
    return {key for key in keys if key}


def is_seen(paper, seen):
    return any(key in seen for key in seen_keys_for(paper))


def merge_paper(existing, new_paper):
    existing["sources"] = append_unique(existing.get("sources"), new_paper.get("sources"))
    existing["matched_keyword"] = append_unique(
        existing.get("matched_keyword"), new_paper.get("matched_keyword")
    )
    existing["matched_keywords"] = append_unique_list(
        existing.get("matched_keywords"), new_paper.get("matched_keywords")
    )
    existing["authors"] = append_unique_list(existing.get("authors"), new_paper.get("authors"))
    existing["topic_tags"] = append_unique_list(existing.get("topic_tags"), new_paper.get("topic_tags"))
    existing["topic_id"] = append_unique(existing.get("topic_id"), new_paper.get("topic_id"))
    existing["topic_name_zh"] = append_unique(existing.get("topic_name_zh"), new_paper.get("topic_name_zh"))
    existing["topic_name_en"] = append_unique(existing.get("topic_name_en"), new_paper.get("topic_name_en"))
    existing["journal_issn"] = append_unique(
        existing.get("journal_issn"), new_paper.get("journal_issn")
    )

    if new_paper.get("cited_by_count", 0) > existing.get("cited_by_count", 0):
        existing["cited_by_count"] = new_paper["cited_by_count"]
        existing["citation_count"] = new_paper["cited_by_count"]

    if new_paper.get("is_open_access"):
        existing["is_open_access"] = True

    for field in [
        "doi",
        "arxiv_id",
        "abstract",
        "publication_date",
        "updated_date",
        "year",
        "journal",
        "venue",
        "journal_issn_l",
        "fwci",
        "openalex_id",
        "semantic_scholar_id",
        "url",
        "pdf_url",
        "obsidian_subdir",
    ]:
        if existing.get(field) in ("", None, MISSING) and new_paper.get(field) not in ("", None):
            existing[field] = new_paper[field]

    return existing


def dedupe(papers):
    deduped = []
    key_to_index = {}
    for paper in papers:
        keys = paper_keys(paper)
        if not keys:
            continue
        existing_index = next((key_to_index[key] for key in keys if key in key_to_index), None)
        if existing_index is not None:
            merge_paper(deduped[existing_index], paper)
            for key in paper_keys(deduped[existing_index]):
                key_to_index[key] = existing_index
        else:
            key_to_index.update({key: len(deduped) for key in keys})
            deduped.append(paper)
    return deduped


def text_relevance_score(text, keyword):
    text_norm = normalize_title(text)
    keywords = [k.strip() for k in str(keyword or "").split(";") if k.strip()]
    if not keywords:
        return 0.0

    best_score = 0.0
    for item in keywords:
        item_norm = normalize_title(item)
        terms = [t for t in item_norm.split() if len(t) > 2]
        if not terms:
            continue
        hits = sum(1 for term in terms if term in text_norm)
        phrase_hit = 1 if item_norm in text_norm else 0
        best_score = max(best_score, min(1.0, (hits / len(terms)) * 0.75 + phrase_hit * 0.25))
    return best_score


def relevance_score(paper, settings):
    title_score = text_relevance_score(paper.get("title", ""), paper.get("matched_keyword"))
    abstract_score = text_relevance_score(paper.get("abstract", ""), paper.get("matched_keyword"))
    title_weight = settings["relevance_title_weight"]
    abstract_weight = settings["relevance_abstract_weight"]
    total_weight = title_weight + abstract_weight
    return (title_score * title_weight + abstract_score * abstract_weight) / total_weight


def recency_score(publication_date, days):
    try:
        published = date.fromisoformat(publication_date)
    except Exception:
        return 0.0
    age = (date.today() - published).days
    if age < 0:
        return 0.0
    return max(0.0, 1.0 - age / max(days, 1))


def score_paper(paper, settings):
    rel = paper.get("relevance_score")
    if rel is None:
        rel = relevance_score(paper, settings)
    citation = min(1.0, math.log1p(paper["cited_by_count"]) / math.log1p(500))
    recency = recency_score(paper["publication_date"], settings["days"])
    oa = 1.0 if paper["is_open_access"] else 0.0
    journal_metric = float(paper.get("journal_metric_score") or 0.0)
    weights = score_weights(settings)

    return (
        weights["relevance"] * rel
        + weights["citation"] * citation
        + weights["recency"] * recency
        + weights["journal"] * journal_metric
        + weights["open_access"] * oa
    )


def score_weights(settings):
    weights = {
        "relevance": settings["score_weight_relevance"],
        "citation": settings["score_weight_citation"],
        "recency": settings["score_weight_recency"],
        "journal": settings["score_weight_journal"],
        "open_access": settings["score_weight_open_access"],
    }
    total = sum(weights.values())
    return {key: value / total for key, value in weights.items()}


def display_metric(value):
    if value in ("", None):
        return MISSING
    if isinstance(value, float):
        return f"{value:.3g}"
    return value


def deepseek_chat_completions_url(settings):
    return settings["deepseek_base_url"].rstrip("/") + "/chat/completions"


def build_deepseek_summary_prompt(paper, settings):
    abstract = truncate_text(paper.get("abstract") or "", 3500) or MISSING
    metadata = [
        f"标题：{paper.get('title') or MISSING}",
        f"作者：{'; '.join(as_list(paper.get('authors'))) or MISSING}",
        f"DOI：{paper.get('doi') or MISSING}",
        f"arXiv ID：{paper.get('arxiv_id') or MISSING}",
        f"期刊/来源：{paper.get('journal') or MISSING}",
        f"发表日期：{paper.get('publication_date') or MISSING}",
        f"引用数：{paper.get('cited_by_count', 0)}",
        f"FWCI：{display_metric(paper.get('fwci'))}",
        f"影响因子：{display_metric(paper.get('journal_impact_factor'))}",
        f"JCR 分区：{paper.get('jcr_quartile') or MISSING}",
        f"主题：{paper.get('topic_name_zh') or MISSING}",
        f"匹配关键词：{paper.get('matched_keyword') or MISSING}",
        f"摘要：{abstract}",
    ]
    if settings["deepseek_json_output"]:
        keys = [
            "summary_zh",
            "problem",
            "method",
            "contributions",
            "experiments",
            "limitations",
            "keywords",
            "reading_priority",
            "why_relevant",
        ]
        return "\n".join(
            [
                "请用中文总结下面这篇学术论文。只能依据给定元数据和摘要，不要猜测不存在的信息。",
                "请只输出一个合法 JSON 对象，不要使用 Markdown 代码块。",
                "JSON 必须包含这些键：" + ", ".join(keys),
                f"`keywords` 最多 {settings['max_keywords_per_paper']} 个，使用中文或英文短语均可。",
                "`reading_priority` 只能是 high、medium、low 之一。",
                "如果摘要不足，请在 limitations 或 why_relevant 中说明信息有限。",
                "",
                *metadata,
            ]
        )

    return "\n".join(
        [
            "请用中文总结下面这篇学术论文。只能依据给定元数据和摘要，不要猜测不存在的信息。",
            "输出 4 条 Markdown bullet，格式固定为：",
            "- 内容概述：...",
            "- 创新点：...",
            "- 研究价值：...",
            "- 注意事项：...",
            "",
            *metadata,
        ]
    )


def parse_deepseek_json_summary(text, settings):
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip()
    candidates = [raw]
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        parsed["keywords"] = as_list(parsed.get("keywords"))[: settings["max_keywords_per_paper"]]
        return parsed
    return None


def structured_summary_to_markdown(summary):
    if not summary:
        return ""
    lines = []
    mapping = [
        ("summary_zh", "内容概述"),
        ("problem", "研究问题"),
        ("method", "方法"),
        ("contributions", "创新点"),
        ("experiments", "实验/验证"),
        ("limitations", "局限性"),
        ("why_relevant", "相关原因"),
    ]
    for key, label in mapping:
        value = summary.get(key)
        if value:
            lines.append(f"- {label}：{value}")
    if summary.get("keywords"):
        lines.append(f"- 关键词：{'; '.join(as_list(summary.get('keywords')))}")
    if summary.get("reading_priority"):
        lines.append(f"- 阅读优先级：{summary.get('reading_priority')}")
    return "\n".join(lines)


def apply_summary_to_paper(paper, raw_summary, structured_summary=None):
    structured_summary = structured_summary or {}
    rendered = structured_summary_to_markdown(structured_summary) or str(raw_summary or "").strip()
    paper["deepseek_summary"] = rendered
    paper["summary"] = rendered
    paper["summary_zh"] = structured_summary.get("summary_zh") or rendered
    paper["summary_structured"] = structured_summary
    paper["extracted_keywords"] = as_list(structured_summary.get("keywords"))
    paper["reading_priority"] = structured_summary.get("reading_priority", "")
    paper["why_relevant"] = structured_summary.get("why_relevant", "")


def summary_cache_key(paper, settings):
    return "|".join(
        [
            paper_key(paper) or normalize_title(paper.get("title")),
            f"model:{settings['deepseek_model']}",
            f"json:{int(settings['deepseek_json_output'])}",
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
                    "突出论文内容、创新点、研究价值和局限；摘要不足时必须说明信息有限。"
                ),
            },
            {
                "role": "user",
                "content": build_deepseek_summary_prompt(paper, settings),
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
            apply_summary_to_paper(paper, "")
        return

    api_key = settings["deepseek_api_key"] or os.environ.get("DEEPSEEK_API_KEY")
    model = settings["deepseek_model"]
    cache = load_summary_cache() if settings["deepseek_cache_enabled"] else {}

    if not api_key:
        for paper in papers:
            apply_summary_to_paper(paper, "未生成（缺少 DEEPSEEK_API_KEY，无法调用 DeepSeek）。")
        return

    for index, paper in enumerate(papers, start=1):
        key = summary_cache_key(paper, settings)
        cached = cache.get(key)
        if settings["deepseek_cache_enabled"] and cached and cached.get("model") == model and cached.get("summary"):
            apply_summary_to_paper(
                paper,
                cached.get("summary", ""),
                cached.get("summary_structured") or {},
            )
            continue

        print(f"Summarizing with DeepSeek ({index}/{len(papers)}): {paper['title']}")
        try:
            raw_summary = call_deepseek_summary(paper, settings, api_key)
            structured_summary = (
                parse_deepseek_json_summary(raw_summary, settings)
                if settings["deepseek_json_output"]
                else None
            )
            apply_summary_to_paper(paper, raw_summary, structured_summary)
            cache[key] = {
                "title": paper["title"],
                "doi": paper.get("doi", ""),
                "arxiv_id": paper.get("arxiv_id", ""),
                "model": model,
                "json_output": settings["deepseek_json_output"],
                "summary": paper["summary"],
                "raw_summary": raw_summary,
                "summary_structured": structured_summary or {},
                "updated_at": date.today().isoformat(),
            }
            if settings["deepseek_cache_enabled"]:
                save_summary_cache(cache)
            time.sleep(settings["deepseek_sleep_seconds"])
        except Exception as exc:
            apply_summary_to_paper(paper, f"未生成（DeepSeek 调用失败：{format_error(exc)}）。")


def append_indented_markdown(lines, text, indent="   "):
    for line in str(text or "").splitlines():
        lines.append(f"{indent}{line}" if line.strip() else "")


def build_full_markdown(papers):
    lines = ["# Paper Radar Latest Results", ""]
    for i, paper in enumerate(papers, start=1):
        lines.append(f"## {i}. {paper['title']}")
        lines.append("")
        lines.append(f"- Topic: {paper.get('topic_name_zh') or MISSING}")
        lines.append(f"- Authors: {'; '.join(as_list(paper.get('authors'))) or MISSING}")
        lines.append(f"- DOI: {paper.get('doi') or MISSING}")
        lines.append(f"- arXiv ID: {paper.get('arxiv_id') or MISSING}")
        lines.append(f"- Journal/Venue: {paper.get('journal') or paper.get('venue') or MISSING}")
        lines.append(f"- Type: {paper.get('work_type') or MISSING}")
        lines.append(f"- Impact factor: {display_metric(paper.get('journal_impact_factor'))}")
        lines.append(f"- JCR quartile: {paper.get('jcr_quartile') or MISSING}")
        lines.append(f"- Date: {paper.get('publication_date') or MISSING}")
        lines.append(f"- Citations: {paper.get('cited_by_count', 0)}")
        lines.append(f"- FWCI: {display_metric(paper.get('fwci'))}")
        lines.append(f"- Sources: {paper.get('sources') or MISSING}")
        lines.append(f"- Matched keyword: {paper.get('matched_keyword')}")
        lines.append(f"- Relevance: {paper.get('relevance_score', 0):.4f}")
        lines.append(f"- Score: {paper.get('score'):.4f}")
        if paper.get("url"):
            lines.append(f"- URL: {paper.get('url')}")
        if paper.get("pdf_url"):
            lines.append(f"- PDF: {paper.get('pdf_url')}")
        if paper.get("deepseek_summary"):
            lines.append("")
            lines.append("### DeepSeek 中文总结")
            lines.append("")
            append_indented_markdown(lines, paper["deepseek_summary"], indent="")
        lines.append("")
    return "\n".join(lines)


def build_title_only_markdown(papers):
    lines = ["# Paper Radar Latest Titles", ""]
    for i, paper in enumerate(papers, start=1):
        lines.append(f"{i}. {paper['title']}")
        if paper.get("doi"):
            lines.append(f"   DOI: {paper['doi']}")
        if paper.get("arxiv_id"):
            lines.append(f"   arXiv: {paper['arxiv_id']}")
        if paper.get("topic_name_zh"):
            lines.append(f"   主题: {paper['topic_name_zh']}")
        if paper.get("deepseek_summary"):
            lines.append("   DeepSeek 总结：")
            append_indented_markdown(lines, paper["deepseek_summary"], indent="   ")
        lines.append("")
    return "\n".join(lines)


def write_outputs(papers, title_only=False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fields = [
        "score",
        "relevance_score",
        "topic_id",
        "topic_name_zh",
        "topic_name_en",
        "topic_tags",
        "title",
        "authors",
        "abstract",
        "work_type",
        "year",
        "doi",
        "arxiv_id",
        "semantic_scholar_id",
        "openalex_id",
        "publication_date",
        "updated_date",
        "journal",
        "venue",
        "journal_issn",
        "journal_issn_l",
        "journal_impact_factor",
        "jcr_quartile",
        "journal_metric_score",
        "journal_metric_match",
        "citation_count",
        "cited_by_count",
        "fwci",
        "is_open_access",
        "keyword",
        "matched_keyword",
        "matched_keywords",
        "source",
        "sources",
        "url",
        "pdf_url",
        "summary",
        "summary_zh",
        "summary_structured",
        "extracted_keywords",
        "reading_priority",
        "why_relevant",
        "deepseek_summary",
    ]

    with CSV_OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            writer.writerow({field: csv_value(paper.get(field, "")) for field in fields})

    full_markdown = build_full_markdown(papers)
    title_only_markdown = build_title_only_markdown(papers)
    MD_OUTPUT.write_text(
        title_only_markdown if title_only else full_markdown,
        encoding="utf-8-sig",
    )
    TITLE_ONLY_OUTPUT.write_text(title_only_markdown, encoding="utf-8-sig")


def paper_tags(paper, settings):
    tags = []
    if settings.get("zotero_tag_prefix"):
        tags.append(settings["zotero_tag_prefix"])
    tags.extend(as_list(paper.get("topic_tags")))
    tags.extend(as_list(paper.get("matched_keywords")))
    tags.extend(as_list(paper.get("extracted_keywords")))
    return append_unique_list([], tags)


def write_zotero_outputs(papers, settings):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = [
        "add_to_zotero",
        "title",
        "authors",
        "year",
        "publication_date",
        "doi",
        "arxiv_id",
        "journal",
        "venue",
        "url",
        "pdf_url",
        "source",
        "sources",
        "matched_keywords",
        "topic",
        "score",
        "relevance_score",
        "summary_zh",
        "tags",
        "notes",
    ]
    with ZOTERO_REVIEW_OUTPUT.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            writer.writerow(
                {
                    "add_to_zotero": "",
                    "title": paper.get("title", ""),
                    "authors": csv_value(paper.get("authors", [])),
                    "year": paper.get("year", ""),
                    "publication_date": paper.get("publication_date", ""),
                    "doi": paper.get("doi", ""),
                    "arxiv_id": paper.get("arxiv_id", ""),
                    "journal": paper.get("journal", ""),
                    "venue": paper.get("venue", ""),
                    "url": paper.get("url", ""),
                    "pdf_url": paper.get("pdf_url", ""),
                    "source": paper.get("source", ""),
                    "sources": paper.get("sources", ""),
                    "matched_keywords": csv_value(paper.get("matched_keywords", [])),
                    "topic": paper.get("topic_name_zh", ""),
                    "score": paper.get("score", ""),
                    "relevance_score": paper.get("relevance_score", ""),
                    "summary_zh": paper.get("summary_zh", ""),
                    "tags": csv_value(paper_tags(paper, settings)),
                    "notes": paper.get("why_relevant", ""),
                }
            )

    ZOTERO_BIB_OUTPUT.write_text(build_bibtex(papers, settings), encoding="utf-8-sig")


def build_bibtex(papers, settings):
    entries = []
    used_keys = set()
    for index, paper in enumerate(papers, start=1):
        key = unique_bibtex_key(paper, index, used_keys)
        used_keys.add(key)
        fields = {
            "title": paper.get("title", ""),
            "author": " and ".join(as_list(paper.get("authors"))),
            "year": paper.get("year", ""),
            "journal": "" if paper.get("journal") == MISSING else paper.get("journal", ""),
            "doi": normalize_doi(paper.get("doi")),
            "url": paper.get("url", ""),
            "abstract": paper.get("abstract", ""),
            "keywords": "; ".join(paper_tags(paper, settings)),
            "note": paper.get("summary_zh", ""),
        }
        if paper.get("arxiv_id"):
            fields["eprint"] = paper["arxiv_id"]
            fields["archivePrefix"] = "arXiv"
        lines = [f"@article{{{key},"]
        for field, value in fields.items():
            if value not in ("", None):
                lines.append(f"  {field} = {{{bibtex_escape(value)}}},")
        lines.append("}")
        entries.append("\n".join(lines))
    return "\n\n".join(entries) + ("\n" if entries else "")


def unique_bibtex_key(paper, index, used_keys):
    authors = as_list(paper.get("authors"))
    first_author = authors[0].split()[-1] if authors else "paper"
    title_words = normalize_title(paper.get("title")).split()
    title_word = title_words[0] if title_words else "radar"
    year = paper.get("year") or "nd"
    base = re.sub(r"[^A-Za-z0-9]+", "", f"{first_author}{year}{title_word}") or f"paper{index}"
    key = base
    suffix = 2
    while key in used_keys:
        key = f"{base}{suffix}"
        suffix += 1
    return key


def bibtex_escape(value):
    return (
        str(value)
        .replace("\\", "\\textbackslash{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", " ")
    )


def obsidian_root(settings, dry_run):
    vault_path = settings.get("obsidian_vault_path")
    if vault_path and not dry_run:
        return Path(vault_path).expanduser(), True
    return OBSIDIAN_OUTPUT_DIR, False


def safe_filename(value, fallback="untitled"):
    value = clean_text(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or fallback)[:140]


def note_filename(paper, index):
    title = safe_filename(paper.get("title"), fallback=f"paper-{index}")
    year = paper.get("year") or "unknown"
    key = first_nonempty(
        paper.get("arxiv_id"),
        normalize_doi(paper.get("doi")).split("/")[-1],
        paper.get("semantic_scholar_id"),
        str(index),
    )
    key = safe_filename(key, fallback=str(index))[:32]
    return f"{year} - {title} - {key}.md"


def yaml_quote(value):
    return json.dumps(str(value or ""), ensure_ascii=False)


def yaml_list(name, values):
    values = as_list(values)
    if not values:
        return [f"{name}: []"]
    lines = [f"{name}:"]
    lines.extend(f"  - {yaml_quote(value)}" for value in values)
    return lines


def obsidian_note_content(paper, settings):
    tags = paper_tags(paper, settings)
    frontmatter = [
        "---",
        f"title: {yaml_quote(paper.get('title'))}",
        *yaml_list("authors", paper.get("authors")),
        f"year: {paper.get('year') or ''}",
        f"publication_date: {yaml_quote(paper.get('publication_date'))}",
        f"updated_date: {yaml_quote(paper.get('updated_date'))}",
        f"doi: {yaml_quote(paper.get('doi'))}",
        f"arxiv_id: {yaml_quote(paper.get('arxiv_id'))}",
        f"url: {yaml_quote(paper.get('url'))}",
        f"pdf_url: {yaml_quote(paper.get('pdf_url'))}",
        f"journal: {yaml_quote(paper.get('journal'))}",
        f"venue: {yaml_quote(paper.get('venue'))}",
        f"source: {yaml_quote(paper.get('source'))}",
        *yaml_list("sources", paper.get("sources")),
        f"topic: {yaml_quote(paper.get('topic_name_zh'))}",
        *yaml_list("matched_keywords", paper.get("matched_keywords")),
        *yaml_list("tags", tags),
        f"status: {yaml_quote(settings['obsidian_note_status'])}",
        f"score: {paper.get('score', 0):.4f}",
        f"relevance_score: {paper.get('relevance_score', 0):.4f}",
        f"created: {yaml_quote(date.today().isoformat())}",
        "---",
    ]

    summary = paper.get("deepseek_summary") or "未生成。"
    abstract = paper.get("abstract") or MISSING
    lines = [
        *frontmatter,
        "",
        f"# {paper.get('title')}",
        "",
        "## 中文总结",
        "",
        summary,
        "",
        "## 相关性",
        "",
        paper.get("why_relevant") or f"匹配关键词：{paper.get('matched_keyword') or MISSING}",
        "",
        "## 摘要",
        "",
        abstract,
        "",
        "## 元数据",
        "",
        f"- DOI: {paper.get('doi') or MISSING}",
        f"- arXiv: {paper.get('arxiv_id') or MISSING}",
        f"- Journal/Venue: {paper.get('journal') or paper.get('venue') or MISSING}",
        f"- Date: {paper.get('publication_date') or MISSING}",
        f"- Sources: {paper.get('sources') or MISSING}",
        f"- Score: {paper.get('score', 0):.4f}",
        "",
        "## Links",
        "",
        f"- URL: {paper.get('url') or MISSING}",
        f"- PDF: {paper.get('pdf_url') or MISSING}",
    ]
    return "\n".join(lines) + "\n"


def write_obsidian_outputs(papers, settings, dry_run=False, logger=None):
    root, writing_vault = obsidian_root(settings, dry_run)
    inbox_dir = root / settings["obsidian_inbox_folder"]
    literature_dir = root / settings["obsidian_literature_folder"]
    topic_dir = root / settings["obsidian_topic_folder"]
    inbox_dir.mkdir(parents=True, exist_ok=True)
    literature_dir.mkdir(parents=True, exist_ok=True)
    if settings["obsidian_topic_index_enabled"]:
        topic_dir.mkdir(parents=True, exist_ok=True)

    note_paths = []
    for index, paper in enumerate(papers, start=1):
        subdirs = as_list(paper.get("obsidian_subdir"))
        target_dir = literature_dir / safe_filename(subdirs[0]) if subdirs and subdirs[0] else literature_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / note_filename(paper, index)
        if path.exists() and not settings["obsidian_overwrite_notes"]:
            if logger:
                logger.add(f"Skipped existing Obsidian note: {path}")
        else:
            path.write_text(obsidian_note_content(paper, settings), encoding="utf-8-sig")
        paper["obsidian_note_path"] = str(path)
        paper["obsidian_note_link"] = f"[[{path.stem}]]"
        note_paths.append(path)

    report_path = inbox_dir / "Paper Radar Report.md"
    report_path.write_text(build_obsidian_report(papers, writing_vault, dry_run), encoding="utf-8-sig")

    if settings["obsidian_topic_index_enabled"]:
        write_obsidian_topic_indexes(papers, topic_dir)

    if logger:
        target = "vault" if writing_vault else "outputs preview"
        logger.add(f"Obsidian export wrote {len(note_paths)} note targets to {target}: {root}")
    return [report_path] + note_paths


def build_obsidian_report(papers, writing_vault, dry_run):
    mode = "dry-run preview" if dry_run else ("vault" if writing_vault else "outputs preview")
    lines = [
        "# Paper Radar Report",
        "",
        f"- Run date: {date.today().isoformat()}",
        f"- Mode: {mode}",
        f"- Papers: {len(papers)}",
        "",
    ]
    for index, paper in enumerate(papers, start=1):
        lines.append(f"## {index}. {paper.get('title')}")
        lines.append("")
        lines.append(f"- Note: {paper.get('obsidian_note_link', '')}")
        lines.append(f"- Topic: {paper.get('topic_name_zh') or MISSING}")
        lines.append(f"- Score: {paper.get('score', 0):.4f}")
        lines.append(f"- DOI: {paper.get('doi') or MISSING}")
        lines.append("")
    return "\n".join(lines)


def write_obsidian_topic_indexes(papers, topic_dir):
    grouped = {}
    for paper in papers:
        topic = paper.get("topic_name_zh") or paper.get("topic_id") or "默认主题"
        grouped.setdefault(topic, []).append(paper)
    for topic, topic_papers in grouped.items():
        path = topic_dir / f"{safe_filename(topic)}.md"
        lines = [
            f"# {topic}",
            "",
            f"Updated: {date.today().isoformat()}",
            "",
        ]
        for paper in topic_papers:
            lines.append(f"- {paper.get('obsidian_note_link', paper.get('title'))} - {paper.get('score', 0):.4f}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def fetch_keyword_papers(keyword, topic, from_date, settings, use_semantic_scholar=True, logger=None):
    papers = []
    semantic_scholar_limited = False

    if settings["openalex_enabled"]:
        (logger.print if logger else print)(f"Searching OpenAlex: {keyword}")
        try:
            source_count = 0
            for work in openalex_search(keyword, from_date, settings):
                paper = complete_paper(extract_openalex_work(work, keyword), keyword, topic, "OpenAlex")
                if paper["is_retracted"] or not paper["title"]:
                    continue
                if is_excluded_work_type(paper, settings):
                    continue
                if is_excluded_title(paper, settings):
                    continue
                if is_excluded_by_topic(paper, topic):
                    continue
                papers.append(paper)
                source_count += 1
            if logger:
                logger.add(f"OpenAlex returned {source_count} usable papers for '{keyword}'.")
        except Exception as exc:
            (logger.print if logger else print)(
                f"Warning: OpenAlex failed for keyword '{keyword}': {format_error(exc)}"
            )

        time.sleep(settings["source_sleep_seconds"])

    if settings["arxiv_enabled"]:
        (logger.print if logger else print)(f"Searching arXiv: {keyword}")
        try:
            source_count = 0
            for entry in arxiv_search(keyword, settings):
                paper = complete_paper(extract_arxiv_entry(entry, keyword), keyword, topic, "arXiv")
                if not paper["title"] or not is_recent_enough(paper["publication_date"], from_date):
                    continue
                if is_excluded_title(paper, settings):
                    continue
                if is_excluded_by_topic(paper, topic):
                    continue
                papers.append(paper)
                source_count += 1
            if logger:
                logger.add(f"arXiv returned {source_count} usable papers for '{keyword}'.")
        except Exception as exc:
            (logger.print if logger else print)(
                f"Warning: arXiv failed for keyword '{keyword}': {format_error(exc)}"
            )

        time.sleep(settings["source_sleep_seconds"])

    if not settings["semantic_scholar_enabled"] or not use_semantic_scholar:
        return papers, semantic_scholar_limited

    (logger.print if logger else print)(f"Searching Semantic Scholar: {keyword}")
    try:
        source_count = 0
        for work in semantic_scholar_search(keyword, from_date, settings):
            paper = complete_paper(
                extract_semantic_scholar_work(work, keyword),
                keyword,
                topic,
                "Semantic Scholar",
            )
            if not paper["title"] or not is_recent_enough(paper["publication_date"], from_date):
                continue
            if is_excluded_title(paper, settings):
                continue
            if is_excluded_by_topic(paper, topic):
                continue
            papers.append(paper)
            source_count += 1
        if logger:
            logger.add(f"Semantic Scholar returned {source_count} usable papers for '{keyword}'.")
    except Exception as exc:
        (logger.print if logger else print)(
            f"Warning: Semantic Scholar failed for keyword '{keyword}': {format_error(exc)}"
        )
        semantic_scholar_limited = is_rate_limited(exc)

    time.sleep(settings["source_sleep_seconds"])
    return papers, semantic_scholar_limited


def is_excluded_work_type(paper, settings):
    work_type = str(paper.get("work_type") or "").strip().lower()
    return bool(work_type and work_type in settings["excluded_work_types"])


def is_excluded_title(paper, settings):
    title = clean_text(paper.get("title") or "").lower()
    return any(pattern in title for pattern in settings["excluded_title_patterns"])


def is_excluded_by_topic(paper, topic):
    if not topic:
        return False
    haystack = normalize_title(f"{paper.get('title', '')} {paper.get('abstract', '')}")
    for keyword in topic.get("exclude_keywords", []):
        normalized = normalize_title(keyword)
        if normalized and normalized in haystack:
            return True
    return False


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
    parser.add_argument("--arxiv", dest="arxiv_enabled", action="store_true", default=None)
    parser.add_argument("--no-arxiv", dest="arxiv_enabled", action="store_false")
    parser.add_argument("--arxiv-max-results", type=int, default=None)
    parser.add_argument("--deepseek-summary", dest="deepseek_summaries", action="store_true", default=None)
    parser.add_argument("--no-deepseek-summary", dest="deepseek_summaries", action="store_false")
    parser.add_argument("--deepseek-base-url", default=None)
    parser.add_argument("--deepseek-api-key", nargs="?", const="", default=None)
    parser.add_argument("--deepseek-model", default=None)
    parser.add_argument("--deepseek-max-tokens", type=int, default=None)
    parser.add_argument("--deepseek-temperature", type=float, default=None)
    parser.add_argument("--deepseek-top-p", type=float, default=None)
    parser.add_argument("--deepseek-json", dest="deepseek_json_output", action="store_true", default=None)
    parser.add_argument("--no-deepseek-json", dest="deepseek_json_output", action="store_false")
    parser.add_argument("--max-keywords", type=int, default=None)
    parser.add_argument("--gpt-summary", dest="deepseek_summaries", action="store_true")
    parser.add_argument("--no-gpt-summary", dest="deepseek_summaries", action="store_false")
    parser.add_argument("--gpt-model", dest="deepseek_model", default=None)
    parser.add_argument("--include-seen", dest="include_seen", action="store_true", default=None)
    parser.add_argument("--no-include-seen", dest="include_seen", action="store_false")
    parser.add_argument("--zotero-export", dest="zotero_export_enabled", action="store_true", default=None)
    parser.add_argument("--no-zotero-export", dest="zotero_export_enabled", action="store_false")
    parser.add_argument("--obsidian-export", dest="obsidian_export_enabled", action="store_true", default=None)
    parser.add_argument("--no-obsidian-export", dest="obsidian_export_enabled", action="store_false")
    parser.add_argument("--obsidian-vault-path", default=None)
    parser.add_argument("--obsidian-overwrite-notes", dest="obsidian_overwrite_notes", action="store_true", default=None)
    parser.add_argument("--no-obsidian-overwrite-notes", dest="obsidian_overwrite_notes", action="store_false")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--log-file", default=None)
    parser.set_defaults(
        arxiv_enabled=None,
        deepseek_summaries=None,
        deepseek_json_output=None,
        zotero_export_enabled=None,
        obsidian_export_enabled=None,
        obsidian_overwrite_notes=None,
    )
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
    if args.arxiv_enabled is not None:
        settings["arxiv_enabled"] = args.arxiv_enabled
    if args.arxiv_max_results is not None:
        settings["arxiv_max_results"] = positive_int(args.arxiv_max_results, "arxiv_max_results")
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
    if args.deepseek_json_output is not None:
        settings["deepseek_json_output"] = args.deepseek_json_output
    if args.max_keywords is not None:
        settings["max_keywords_per_paper"] = positive_int(args.max_keywords, "max_keywords")
    if args.zotero_export_enabled is not None:
        settings["zotero_export_enabled"] = args.zotero_export_enabled
    if args.obsidian_export_enabled is not None:
        settings["obsidian_export_enabled"] = args.obsidian_export_enabled
    if args.obsidian_vault_path is not None:
        settings["obsidian_vault_path"] = args.obsidian_vault_path.strip()
    if args.obsidian_overwrite_notes is not None:
        settings["obsidian_overwrite_notes"] = args.obsidian_overwrite_notes
    if args.log_file is not None:
        settings["log_file"] = args.log_file.strip()

    if settings["min_score"] < 0:
        raise ValueError("min_score must be greater than or equal to 0.")
    if not settings["deepseek_base_url"]:
        raise ValueError("deepseek_base_url cannot be empty.")
    if not settings["deepseek_model"]:
        raise ValueError("deepseek_model cannot be empty.")

    logger = RunLogger()
    from_date = (date.today() - timedelta(days=settings["days"])).isoformat()
    topics = read_search_topics()
    metrics = load_journal_metrics()
    enabled_sources = [
        source
        for source, enabled in [
            ("OpenAlex", settings["openalex_enabled"]),
            ("arXiv", settings["arxiv_enabled"]),
            ("Semantic Scholar", settings["semantic_scholar_enabled"]),
        ]
        if enabled
    ]
    logger.add("Paper Radar run started.")
    logger.add(f"From date: {from_date}; top: {settings['top']}; min_relevance: {settings['min_relevance']}")
    logger.add(f"Enabled sources: {', '.join(enabled_sources) or 'none'}")
    logger.add(f"Topics: {len(topics)}; dry_run: {args.dry_run}")

    all_papers = []
    use_semantic_scholar = True
    for topic in topics:
        logger.print(f"Topic: {topic['name_zh']} / {topic['name_en']}")
        for keyword in topic["keywords"]:
            keyword_papers, semantic_scholar_limited = fetch_keyword_papers(
                keyword,
                topic,
                from_date,
                settings,
                use_semantic_scholar=use_semantic_scholar,
                logger=logger,
            )
            all_papers.extend(keyword_papers)
            if semantic_scholar_limited:
                use_semantic_scholar = False
                logger.print(
                    "Warning: Semantic Scholar rate limit reached; skipping it for remaining keywords."
                )

    logger.add(f"Fetched raw papers: {len(all_papers)}")
    papers = dedupe(all_papers)
    logger.add(f"After dedupe: {len(papers)}")
    apply_journal_metrics(papers, metrics)
    seen = load_seen()

    if not settings["include_seen"]:
        before_seen_filter = len(papers)
        papers = [paper for paper in papers if not is_seen(paper, seen)]
        logger.add(f"Filtered seen papers: {before_seen_filter - len(papers)}")

    for paper in papers:
        paper["relevance_score"] = relevance_score(paper, settings)
        paper["score"] = score_paper(paper, settings)

    before_relevance_filter = len(papers)
    papers = [paper for paper in papers if paper["relevance_score"] >= settings["min_relevance"]]
    logger.add(f"Filtered by relevance: {before_relevance_filter - len(papers)}")
    before_score_filter = len(papers)
    papers = [paper for paper in papers if paper["score"] >= settings["min_score"]]
    logger.add(f"Filtered by score: {before_score_filter - len(papers)}")
    papers.sort(key=lambda p: p["score"], reverse=True)
    papers = papers[: settings["top"]]
    logger.add(f"Selected ranked papers: {len(papers)}")

    enrich_deepseek_summaries(papers, settings)
    write_outputs(papers, title_only=settings["title_only"])
    logger.add(f"Wrote core outputs: {CSV_OUTPUT}, {MD_OUTPUT}, {TITLE_ONLY_OUTPUT}")

    if settings["zotero_export_enabled"]:
        write_zotero_outputs(papers, settings)
        logger.add(f"Wrote Zotero outputs: {ZOTERO_REVIEW_OUTPUT}, {ZOTERO_BIB_OUTPUT}")

    if settings["obsidian_export_enabled"]:
        write_obsidian_outputs(papers, settings, dry_run=args.dry_run, logger=logger)

    if args.dry_run:
        logger.print("Dry run: skipped updating data/seen_papers.json.")
    else:
        for paper in papers:
            key = paper_key(paper)
            if not key:
                continue
            seen[key] = {
                "title": paper["title"],
                "doi": paper.get("doi", ""),
                "arxiv_id": paper.get("arxiv_id", ""),
                "first_seen": date.today().isoformat(),
            }
        save_seen(seen)
        logger.add(f"Updated seen file: {SEEN_FILE}")

    log_path = resolve_output_path(settings["log_file"])
    logger.write(log_path)

    print(f"Done. Wrote: {CSV_OUTPUT}")
    print(f"Done. Wrote: {MD_OUTPUT}")
    print(f"Done. Wrote: {TITLE_ONLY_OUTPUT}")
    if settings["zotero_export_enabled"]:
        print(f"Done. Wrote: {ZOTERO_REVIEW_OUTPUT}")
        print(f"Done. Wrote: {ZOTERO_BIB_OUTPUT}")
    if settings["obsidian_export_enabled"]:
        print(f"Done. Wrote Obsidian export under: {obsidian_root(settings, args.dry_run)[0]}")
    print(f"Done. Wrote: {log_path}")


if __name__ == "__main__":
    main()
