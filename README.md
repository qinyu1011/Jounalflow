# JournalFlow — 期刊投稿经验智能分析平台

> 输入期刊名称，自动抓取 LetPub 投稿经验 → LLM 结构化提取审稿时间节点 → 可视化统计看板

---

## 项目简介

学者在投稿前往往需要了解目标期刊的审稿周期、大修概率、编辑处理速度等信息。LetPub 积累了大量用户投稿经验，但这些经验以**自由文本**形式存在，难以直接比较和统计。

JournalFlow 通过 LLM 将非结构化投稿经验转化为精细的时间节点数据（`T_Submit`、`T_UnderReview`、`T_Accept` 等），生成可量化的审稿流程统计，帮助研究者在投稿前做出更理性的期刊选择。

---

## 功能特性

- **智能期刊搜索**：支持输入缩写（如 `TPAMI`），自动调用 LLM 扩展为全名并二次确认
- **自动抓取评论**：基于 LetPub JSON API，支持翻页抓取，自动过滤无时间信息的纯文字评论
- **LLM 结构化提取**：将自然语言投稿经验解析为 15 个精细时间节点，支持最多三轮修改流程
- **多维统计分析**：10 个派生审稿周期的均值/中位数/分布统计
- **实时可视化看板**：审稿流程时间线、各阶段耗时表、结果分布图、月度趋势等
- **SSE 实时进度**：前端实时显示每条评论的处理进度

---

## 技术架构

```
用户输入期刊名
    ↓
[Flask 后端] /api/expand → LLM 识别缩写 → 前端确认弹窗
    ↓
[LetPub 爬虫] letpub_scraper.py
  - 入口A: AJAX JSON API（直连）
  - 入口B: HTML 搜索结果（备用）
  - 过滤纯文字评论（无时间节点价值）
    ↓
[LLM 提取] llm_extractor.py
  - 并发 5 线程调用 LLM
  - 提取 T_Submit / T_WithEditor / T_UnderReview / T_Decision / T_Accept 等
  - 自动年份补全（基于发表时间推算）
    ↓
[统计分析] analyzer.py
  - 10 个派生周期统计（均值/中位数/最小/最大/标准差）
    ↓
[前端看板] templates/index.html
  - 审稿流程 Pipeline 可视化
  - 各阶段耗时表 + 图表
  - 评论明细表（含所有 T_ 字段）
```

---

## LLM 时间节点体系

| 字段 | 含义 |
|------|------|
| `T_Submit` | 投稿日期 |
| `T_WithEditor_1/2/3` | 进入编辑处理（一/二/三次） |
| `T_UnderReview_1/2/3` | 送审日期（一/二/三审） |
| `T_FirstDecision` | 一审结果（日期 + 类型） |
| `T_Revision_Submit_1/2` | 作者提交修改稿（第一/二次） |
| `T_SecondDecision` | 二审结果 |
| `T_ThirdDecision` | 三审结果 |
| `T_Accept` | 录用日期 |
| `final_result` | 最终结果（大修/小修/拒稿/在审/未知） |

**关键设计**：评论者几乎从不写年份（如"3.5投稿，8月大修"），LLM 以网站标注发表时间为基准自动补全年份，包括跨年判断。

---

## 统计维度（10个派生周期）

| 编号 | 周期 | 计算方式 |
|------|------|---------|
| ① | 初审编辑处理速度 | T_WE₁ − T_Submit |
| ② | 投稿到首次送审 | T_UR₁ − T_Submit |
| ③ | 一审周期 | T_1stDecision − T_UR₁ |
| ④ | 作者一次修改耗时 | T_Rev₁ − T_1stDecision |
| ⑤ | 修回后编辑处理（二审） | T_UR₂ − T_Rev₁ |
| ⑥ | 二审周期 | T_Accept − T_UR₂ |
| ⑦ | 作者二次修改耗时 | T_Rev₂ − T_2ndDecision |
| ⑧ | 修回后编辑处理（三审） | T_UR₃ − T_Rev₂ |
| ⑨ | 三审周期 | T_Accept − T_UR₃ |
| ⑩ | 整体周期 | T_Accept − T_Submit |

---

## 快速开始

### 1. 安装依赖

```bash
pip install flask requests beautifulsoup4 openai
```

### 2. 配置 `config.py`

```python
LETPUB_COOKIE = "..."        # 登录 letpub.com.cn 后从浏览器 F12 复制
LLM_API_KEY   = "sk-..."     # API Key
LLM_BASE_URL  = "https://api.openai.com/v1"
LLM_MODEL     = "gpt-4o-mini"
PORT          = 6006
```

### 3. 启动服务

```bash
python app.py
```

访问 `http://localhost:6006`，输入期刊名称（支持全名或缩写）即可开始分析。

---

## API 与成本说明

### 使用的模型与接口

| 用途 | 模型 | 接口 |
|------|------|------|
| 时间节点提取（主要调用） | `gpt-4o-mini` | OpenAI 兼容 API |
| 期刊缩写扩展 | `gpt-4o-mini` | 同上 |

### 单次运行成本估算

以分析 **50 条评论**为例：

| 项目 | 数值 |
|------|------|
| 每条评论 Input tokens | ~1,000 tokens |
| 每条评论 Output tokens | ~250 tokens |
| 单次调用费用（gpt-4o-mini） | ~$0.005 |
| 50 条总费用 | **~$0.25（约 ¥1.8）** |

> 实测数据来源：holdai.top 平台账单截图（2026-03-09）

### 成本优化策略

- **并发调用**：5 线程并发，总时间缩短约 5 倍
- **精简 Prompt**：限制 `max_tokens=400`，避免推理模型的冗长思考输出
- **前置过滤**：爬虫阶段过滤不含数字的纯文字评论，减少无效 LLM 调用
- **避免使用推理模型**：`deepseek-r1` 等推理模型在此任务上比普通模型慢 5–10 倍且无精度提升

---

## 项目结构

```
journalflow/
├── app.py              # Flask 后端 + SSE 实时推送
├── letpub_scraper.py   # LetPub 爬虫（JSON API + HTML 备用）
├── llm_extractor.py    # LLM 结构化提取时间线（并发版）
├── analyzer.py         # 统计分析（10个派生周期）
├── agent.py            # LangChain Agent（可选）
├── config.py           # Cookie / API Key / 服务器配置
├── templates/
│   └── index.html      # 前端看板
└── requirements.txt
```

---

## 部署

项目部署于 AutoDL 云服务器，通过公网端口访问：

```
访问地址：http://<服务器IP>:<端口>
运行环境：Python 3.12 / Miniconda
启动命令：python app.py
```

---

## 已知限制

- LetPub Cookie 有效期约数天，需定期更新
- LLM 年份推断在少数边缘情况下可能出错（如评论跨越多年）
- 三审统计样本量通常较少（大多数期刊只有一到两轮修改）
