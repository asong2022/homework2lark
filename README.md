# homework2lark · 小学数学智能错题学习系统

[![CI](https://github.com/asong2022/homework2lark/actions/workflows/ci.yml/badge.svg)](https://github.com/asong2022/homework2lark/actions/workflows/ci.yml)

把作业图片、PDF、Word 或单题截图发给 AI，经过教师确认后保存到飞书多维表格；以后继续让 AI 从错题库生成变式题、个人精准练习和再练内容。

教师不用手工建表，不用理解 OCR、FastAPI、字段 ID 或命令行。Codex、Hermes 等能操作电脑的 AI 是唯一入口；没有需要额外安装或打开的 Web 前端。

## 最简单的安装方式

把本仓库地址发给 AI：

<https://github.com/asong2022/homework2lark>

然后把下面这段话原样发给它：

> 请帮我安装并初始化 homework2lark。先阅读仓库的 README、AI_INSTALL.md 和 shi-homework2lark/SKILL.md，使用仓库内置的 onboarding.py 一直处理到 verify 返回 ready。每次只问我一个真正缺失的信息；默认使用 PaddleOCR-VL-1.6，由我在对话中选择题目，你负责从原图保存完整题目边界，不强制配置 Yescan；用内置空白模板创建我的飞书 Base。配置完成后直接告诉我“可以开始发作业了”。

首次使用通常只需要教师完成两件事：

1. PaddleOCR / AI Studio Token；
2. 一次飞书用户授权。

Yescan 自动候选框、当前年级和学期日期都是可选项，不阻塞开始收题；教师以后需要时再让 AI 配置即可。

详细的 AI 执行清单见 [AI_INSTALL.md](./AI_INSTALL.md)。

## 配置好以后怎么用

继续在同一个 AI 对话里说，例如：

- “收集错题到飞书。”
- “新增今天夸克扫描王里的错题，历史已有的不要导入。”
- “这是一份空白卷和一批已批改作业，统计共性错题，不记姓名。”
- “这是班级名单和已批改作业，按学生整理错题。”
- “从飞书错题库选 5 道题，每题生成 2 道变式题并写回。”
- “按班级名单给每个学生生成一份个人练习纸。”
- “练习纸的题图缩小到 70%，其他字号、页边距和自然分页不变。”
- “这是上次练习的批改 PDF，把再练结果反馈到错题库。”
- “这 12 张图每张都是一道题，请逐张收录；中间失败的下次接着补。”

第一次收题时，AI 会让教师明确选择一种方式，不替教师猜：

1. **教师精选**：只提供题目或空白卷，由教师指定要收录的题号；
2. **匿名批改统计**：空白卷 + 已批改作业，统计哪些题错得多，不记录姓名；
3. **实名绑定统计**：空白卷 + 已批改作业 + 班级名单，形成学生个人错题关系。

无论哪种方式，一道题始终是一个完整资产：题干文字、文字选项和题干图片不会被拆成多道题。外层题号单独保存，不重复进入可复用题干。

复杂表格题也遵守同一规则：完整原图是视觉事实，文本转写保留表头、单位、空白格和脚注；影响解题的单元格看不清时，AI 会停下来请教师确认，不猜数字。

## 飞书 Base 里有什么

内置空白模板会创建四张表：

| 表 | 用途 |
|---|---|
| 错题页面 | 保存来源页、日期、年级、来源、页码和原始页面 |
| 错题题目 | 保存完整原题、题干图文、答案、知识点、核心素养和统计结果 |
| 错题记录 | 按“同一道题 + 同一种错误原因”归组真实作答和对应学生 |
| 变式题 | 每道变式独立成行，并关联唯一原题 |

模板没有示例记录、学生名单、固定年级、固定学期、审核状态或 Fake 数据。`对应学生` 初始为空，只有教师自己的私有名单流程会填入选项。

“教学优先”不是永久标签。AI 只在教师给出年级和学期日期后创建范围化视图，筛选该年级、该时间段内的高频错题，避免把多年级、跨学期的历史错题混在一起。

## 这套系统坚持什么

- **教师确认内容，不维护审核状态**：OCR 是初稿，教师确认后的非空修订即可入库。
- **Base 是中转核心，本地证据不丢**：飞书负责长期筛选复用；原图、裁图、OCR 原文和修订历史保存在本机。
- **先收原题，再谈举一反三**：变式题和练习都从已经入库的真实错题出发，并能写回 Base。
- **真实作答先于错误归因**：先记录典型错例和可见错误表现，再由 AI 与教师共同判断原因。
- **答案解析可选**：变式题只要题目完整就能用于练习，答案解析可稍后补。
- **最少必要字段**：教师常用字段显示在视图里；稳定 ID 等幂等字段保留但不占用日常操作界面。

## OCR 与题图

默认 OCR 是官方托管 `PaddleOCR-VL-1.6`，无需教师在本地部署模型或 GPU。题图不交给 OCR 猜：完整题目裁图和题干图片都以原始高清页面为视觉依据，从原像素提取，上传飞书后再回读检查。

未配置 Yescan 时，教师只需在对话中说出题号，AI 根据原始页面保存完整题目边界，不会产生虚假的“自动检测结果”。边界确实看不清时，AI 会请教师补一张单题截图。Yescan 只是可选的整页候选路径，不是错题学习闭环的前提。

也可以把夸克扫描王“试卷宝·错题本”作为可选单题来源。第一次连接只建立现有 ID 基线，下载和入库均为 0；以后说“新增今天/本次的夸克错题”就会直接处理全部待收录新增题，不再逐题询问。说“看看新增了哪些”则只展示，明确指定部分题目时仍可选择式导入。这里的“今天”表示本地基线或上次同步后尚未处理的新题，不依赖夸克私有时间字段。该入口依赖夸克 App 私有接口，可能随 App 更新而需要适配。

本仓库没有 Web 或手机 App。教师只面对 AI 对话和自己的飞书 Base。

## 隐私边界

- PaddleOCR Token、Yescan Key、飞书身份与本地 `.env` 不进入 Git。
- 班级名单、学号、原始作业、OCR 原文、练习 manifest 和学生反馈保持私有，不进入公开模板。
- 飞书默认只保存名单中的准确姓名；学号用于本地身份核对和个人练习纸，不写入稳定 ID 或普通日志。
- 含学生信息的材料发送到第三方 OCR 前，AI 仍应说明服务商和范围。
- 初始化器不会修改或清理已有业务 Base；同名库冲突时会停止，不会“取第一个”。

## 给开发者

主要技术栈：Python 3.11/3.12、FastAPI、SQLAlchemy、Alembic、SQLite，以及用户身份下的 `lark-cli`。

首次安装运行时：

```powershell
uv sync --directory apps/api --all-groups
uv run --directory apps/api alembic upgrade head
```

启动 API：

```powershell
uv run --directory apps/api uvicorn --app-dir src mistake_notebook_api.main:app --port 8000
```

初始化器与 Skill 入口：

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . check
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . verify
python -X utf8 .agents/skills/shi-homework2lark/scripts/doctor.py
```

API 健康检查：`http://127.0.0.1:8000/api/v1/health`。架构和开发约定从 [docs/index.md](./docs/index.md) 与 [.trellis/spec/](./.trellis/spec/) 开始。

Windows 本机也可运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-local.ps1`，只准备并启动 API，不打开网页，不覆盖已有 `.env` 或业务数据。

质量门：

```powershell
uv run --directory apps/api ruff format --check .
uv run --directory apps/api ruff check .
uv run --directory apps/api mypy src
uv run --directory apps/api pytest -q
uv run --directory apps/api --with python-docx python -m unittest discover -s ../../.agents/skills/shi-homework2lark/tests -p 'test_*.py'
uv run --directory apps/api python ../../.agents/skills/shi-homework2lark/scripts/package_bundle.py verify --package ../../artifacts/skills/shi-homework2lark.skill
```

公开自动化测试不使用教师 Token，也不消耗 PaddleOCR 额度；真实云端冒烟测试必须显式开启。
