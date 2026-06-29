# paper-radar

Paper Radar 是一个轻量文献雷达入口。它按主题和关键词检索最近论文，合并 OpenAlex、Semantic Scholar、arXiv 结果，按关键词相关度、引用、时效性、期刊指标和开放获取情况排名，并可调用 DeepSeek 生成中文结构化总结。

默认入口保持不变：

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py
```

## 安装

当前脚本只使用 Python 标准库，不需要额外安装依赖。建议使用 Python 3.10+。

## 配置文件

公开参数放在 `config/settings.json`，可提交到 Git。私密参数放在 `config/settings.local.json`，该文件已被 `.gitignore` 忽略，不会上传远程仓库。可从示例复制：

```powershell
Copy-Item config\settings.local.example.json config\settings.local.json
```

加载顺序是：内置默认值、`config/settings.json`、`config/settings.local.json`、命令行参数。后面的配置会覆盖前面的配置。

### 主题和关键词

优先读取 `config/topics.yaml`：

```yaml
topics:
  underwater_manipulation:
    name_zh: 水下机器人操作
    name_en: Underwater Robotic Manipulation
    obsidian_subdir: underwater-manipulation
    tags:
      - underwater-robotics
    keywords:
      - underwater robotic grasping
    exclude_keywords:
      - underwater image enhancement
```

如果 `config/topics.yaml` 不存在，会回退到 `config/keywords.txt`，一行一个关键词。

### 期刊指标

`config/journal_metrics.csv` 支持 ISSN 或期刊名匹配影响因子和 JCR 分区：

```csv
journal,issn,impact_factor,jcr_quartile
npj Microgravity,2373-8065,,Q1
```

匹配优先级是 ISSN，然后是 journal name。缺失指标会显示为 `未找到`，脚本不会猜测影响因子或分区。

### 私密参数

`config/settings.local.json` 适合放：

```json
{
  "openalex_mailto": "you@example.com",
  "semantic_scholar_api_key": "your-semantic-scholar-api-key",
  "deepseek_base_url": "https://api.deepseek.com",
  "deepseek_api_key": "your-deepseek-api-key"
}
```

对应环境变量也可作为兜底：`OPENALEX_MAILTO`、`SEMANTIC_SCHOLAR_API_KEY`、`DEEPSEEK_API_KEY`。

## 常用参数

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --days 365 --top 30 --min-score 0
```

常用开关：

- `--arxiv` / `--no-arxiv`：启用或关闭 arXiv 补充源。
- `--arxiv-max-results 50`：每个关键词最多拉取多少条 arXiv 结果。
- `--deepseek-summary` / `--no-deepseek-summary`：启用或关闭 DeepSeek 中文总结。
- `--deepseek-json` / `--no-deepseek-json`：启用或关闭结构化 JSON 总结模式。
- `--max-keywords 8`：限制每篇论文提取关键词数量。
- `--include-seen` / `--no-include-seen`：是否包含已经写入 `data/seen_papers.json` 的论文。
- `--zotero-export` / `--no-zotero-export`：启用或关闭 Zotero 导出文件。
- `--obsidian-export` / `--no-obsidian-export`：启用或关闭 Obsidian Markdown 导出。
- `--obsidian-vault-path "D:\Obsidian\Vault"`：临时指定 Obsidian vault。
- `--obsidian-overwrite-notes` / `--no-obsidian-overwrite-notes`：是否覆盖已有笔记。
- `--dry-run`：测试运行，不更新 `data/seen_papers.json`，也不会写入真实 Obsidian vault。
- `--log-file outputs/run_log.txt`：指定运行日志路径。

## DeepSeek 总结

启用 `deepseek_summaries` 后，脚本会在排名完成后调用 DeepSeek，对每篇入选论文生成中文总结，并附在 `outputs/latest_titles_title_only.md` 的每篇文章之后。

当 `deepseek_json_output` 为 `true` 时，脚本会要求模型返回 JSON，并解析这些字段：`summary_zh`、`problem`、`method`、`contributions`、`experiments`、`limitations`、`keywords`、`reading_priority`、`why_relevant`。如果模型返回的不是合法 JSON，会保留原始总结文本。

总结缓存写入 `data/deepseek_summaries.json`，缓存键会区分论文、模型和 JSON 模式，避免不同模型或输出模式互相污染。

## 输出

核心输出：

- `outputs/ranked_papers.csv`：完整机器可读排名。
- `outputs/latest_titles.md`：完整 Markdown 结果。
- `outputs/latest_titles_title_only.md`：标题版 Markdown，包含每篇论文的 DeepSeek 中文总结。
- `outputs/run_log.txt`：运行日志。

Zotero 辅助输出：

- `outputs/zotero_review_queue.csv`：人工审核队列，包含 `add_to_zotero` 列，方便筛选。
- `outputs/zotero_import.bib`：可手动导入 Zotero 的 BibTeX。

Obsidian 输出：

- 如果 `obsidian_vault_path` 为空，写到 `outputs/obsidian/`。
- 如果配置了真实 vault，正常运行会写入该 vault。
- `--dry-run` 时即使配置了真实 vault，也只写 `outputs/obsidian/` 预览。
- 默认目录包括 `00_Inbox`、`01_Literature_Notes`、`03_Topic_Index`，都可在 `settings.json` 调整。

## Zotero / Obsidian 工作流

建议先用 `--dry-run --no-deepseek-summary` 检查检索质量，再启用 DeepSeek 和导出：

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --dry-run --no-deepseek-summary --top 10
```

Zotero 当前是手动导入模式：先查看 `zotero_review_queue.csv`，确认需要保留的论文，再导入 `zotero_import.bib`。这样不会自动污染 Zotero 库。

Obsidian 当前直接输出 Markdown。若你在 Codex/MCP 环境中使用本项目，不需要额外 MCP 服务；需要自动写 Zotero 或 Obsidian 插件 API 时，可以在此基础上继续扩展。

## 测试

编译检查：

```powershell
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'paper-radar-pycache'
python -m py_compile .agents\skills\paper-radar\scripts\paper_radar.py
```

无 DeepSeek key 的安全运行：

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --dry-run --deepseek-api-key= --top 3
```

不调用 LLM 的快速运行：

```powershell
python .agents\skills\paper-radar\scripts\paper_radar.py --dry-run --no-deepseek-summary --top 3
```
