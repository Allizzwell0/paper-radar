# paper-radar

Paper Radar 根据关键词检索近期论文，合并 OpenAlex 和 Semantic Scholar 结果，去重、打分并输出排行榜。

## 配置

关键词写在 `config/keywords.txt`，一行一个关键词，支持用 `#` 注释。

默认运行参数写在 `config/settings.json`：

```json
{
  "days": 365,
  "top": 30,
  "title_only": false,
  "min_score": 0.0,
  "min_relevance": 0.45,
  "include_seen": false,
  "request_timeout_seconds": 30,
  "source_sleep_seconds": 0.5,
  "user_agent": "paper-radar/1.0",
  "openalex_enabled": true,
  "openalex_per_page": 50,
  "excluded_work_types": [
    "dataset"
  ],
  "excluded_title_patterns": [
    "data and code for"
  ],
  "semantic_scholar_enabled": true,
  "semantic_scholar_per_page": 50,
  "deepseek_summaries": true,
  "deepseek_base_url": "https://api.deepseek.com",
  "deepseek_model": "deepseek-v4-flash",
  "deepseek_summary_max_tokens": 500,
  "deepseek_temperature": 0.2,
  "deepseek_top_p": 1.0,
  "deepseek_timeout_seconds": 90,
  "deepseek_sleep_seconds": 0.3,
  "deepseek_cache_enabled": true,
  "deepseek_thinking_disabled": true,
  "relevance_title_weight": 0.75,
  "relevance_abstract_weight": 0.25,
  "score_weight_relevance": 0.65,
  "score_weight_citation": 0.15,
  "score_weight_recency": 0.10,
  "score_weight_journal": 0.07,
  "score_weight_open_access": 0.03
}
```

- `days`：检索最近多少天的论文。
- `top`：最多输出多少篇。
- `title_only`：为 `true` 时，`outputs/latest_titles.md` 使用标题版格式；无论该值如何，脚本都会生成 `outputs/latest_titles_title_only.md`。
- `min_score`：过滤低于该分数的论文。
- `min_relevance`：过滤低于该相关度的论文，相关度基于标题和摘要对关键词的匹配；调高会更严格。
- `include_seen`：是否包含已经写入 `data/seen_papers.json` 的论文。
- `request_timeout_seconds`：OpenAlex、Semantic Scholar 等普通 HTTP 请求超时。
- `source_sleep_seconds`：不同学术数据源请求之间的暂停秒数。
- `user_agent`：请求 API 时使用的 User-Agent。
- `openalex_enabled` / `semantic_scholar_enabled`：是否启用对应数据源。
- `openalex_per_page` / `semantic_scholar_per_page`：每个关键词从对应数据源最多拉取多少条。
- `excluded_work_types`：排除的 OpenAlex work type；默认排除 `dataset`，避免补充数据/代码包排到论文前面。
- `excluded_title_patterns`：按标题关键词排除结果；默认排除 `Data and Code for` 这类补充材料。
- `deepseek_summaries`：为 `true` 时，在排名完成后调用 DeepSeek 生成中文论文总结，并附到 `outputs/latest_titles_title_only.md` 每篇文章之后。
- `deepseek_base_url`：DeepSeek API 地址，默认 `https://api.deepseek.com`。
- `deepseek_model`：用于生成总结的 DeepSeek 模型，可用 `--deepseek-model` 覆盖。
- `deepseek_summary_max_tokens`：每篇文章总结的最大输出 token 数。
- `deepseek_temperature` / `deepseek_top_p`：DeepSeek 采样参数。
- `deepseek_timeout_seconds`：DeepSeek 总结请求超时。
- `deepseek_sleep_seconds`：每篇文章总结之间的暂停秒数。
- `deepseek_cache_enabled`：是否启用 `data/deepseek_summaries.json` 总结缓存。
- `deepseek_thinking_disabled`：是否在请求 DeepSeek 时附带关闭 thinking 的参数。
- `relevance_title_weight` / `relevance_abstract_weight`：标题和摘要在相关度计算中的权重。
- `score_weight_relevance` / `score_weight_citation` / `score_weight_recency` / `score_weight_journal` / `score_weight_open_access`：总分各项权重；脚本会自动归一化，当前默认更偏重关键词相关度。

私密参数写在 `config/settings.local.json`。这个文件已在 `.gitignore` 中忽略，不会被 Git 提交；可以参考 `config/settings.local.example.json`：

```json
{
  "openalex_mailto": "you@example.com",
  "semantic_scholar_api_key": "your-semantic-scholar-api-key",
  "deepseek_base_url": "https://api.deepseek.com",
  "deepseek_api_key": "your-deepseek-api-key"
}
```

加载顺序是默认值、`config/settings.json`、`config/settings.local.json`，后面的配置会覆盖前面的配置。`deepseek_api_key`、`semantic_scholar_api_key`、`openalex_mailto` 为空时，脚本还会尝试读取对应环境变量。

期刊指标写在 `config/journal_metrics.csv`：

```csv
journal,issn,impact_factor,jcr_quartile
npj Microgravity,2373-8065,,
```

匹配优先级是 ISSN，其次是期刊名。`jcr_quartile` 支持 `Q1`、`Q2`、`Q3`、`Q4`。没有指标时会标为 `未找到`，不会猜测影响因子或分区。

## 运行

使用配置文件运行：

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py
```

命令行参数会覆盖 `config/settings.json` 和 `config/settings.local.json`：

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --days 14 --top 20 --min-score 0.2
```

常用参数：

- `--title-only`：让 `outputs/latest_titles.md` 也使用标题版格式。
- `--no-title-only`：强制 `outputs/latest_titles.md` 使用完整格式。
- `--deepseek-summary` / `--no-deepseek-summary`：启用或关闭 DeepSeek 中文总结。
- `--deepseek-base-url` / `--deepseek-api-key`：临时指定 DeepSeek 地址或 key；涉及 key 时更建议使用 `config/settings.local.json`。
- `--deepseek-model`：临时指定总结模型。
- `--deepseek-max-tokens` / `--deepseek-temperature` / `--deepseek-top-p`：临时覆盖 DeepSeek 生成参数。
- `--include-seen`：包含已经记录在 `data/seen_papers.json` 中的论文，适合测试或重新生成输出。
- `--no-include-seen`：强制排除已见论文。

可选环境变量会在对应配置为空时作为兜底：

- `OPENALEX_MAILTO`：传给 OpenAlex 的联系邮箱。
- `SEMANTIC_SCHOLAR_API_KEY`：Semantic Scholar API key，可提高限流额度。
- `DEEPSEEK_API_KEY`：调用 DeepSeek 生成中文总结所需的 API key。

如果启用了 `deepseek_summaries` 但配置和环境变量中都没有 `DEEPSEEK_API_KEY`，脚本会继续生成排名，并在标题版输出中标注总结未生成。

## 输出

- `outputs/ranked_papers.csv`：机器可读结果，包含分数、DOI、期刊、影响因子、JCR 分区、来源等字段。
- `outputs/latest_titles.md`：默认完整 Markdown 结果。
- `outputs/latest_titles_title_only.md`：固定生成的标题版 Markdown 结果；启用 DeepSeek 总结时，每篇文章标题和 DOI 后会附中文总结。
- `data/seen_papers.json`：已见论文记录，用于默认跳过历史结果。
- `data/deepseek_summaries.json`：DeepSeek 总结缓存，避免重复调用同一模型总结同一篇文章。
