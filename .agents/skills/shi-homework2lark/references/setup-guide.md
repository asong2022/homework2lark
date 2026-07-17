# 一键安装与配置

本指南只供 AI 执行。教师的目标是“发仓库地址，回答少量必要问题，然后开始发作业”，不是学习 Python、CLI、Token 或 Base 字段。

## 成功标准

完成后必须同时满足：

- 完整仓库已在本机，API 的 Python 3.11/3.12 环境可用；
- `shi-homework2lark` 已安装到当前 Agent 可发现的 skills 根；
- 官方托管 `PaddleOCR-VL-1.6` 已配置；
- `lark-cli` 以教师自己的飞书用户身份登录；
- 飞书中存在唯一、结构正确的四表空白错题库；
- `onboarding.py verify` 返回 `status=ready`。

Web 不是必需项。只有教师需要在电脑上手动画框时才安装 Node 依赖并启动 Web；纯对话收题、Base 选题、变式和练习不因 Web 未启动而被阻塞。

## AI 执行顺序

### 1. 获取仓库并安装 Skill

仓库地址：`https://github.com/asong2022/homework2lark`。

Codex 优先使用官方 `skill-installer` 从仓库子目录 `.agents/skills/shi-homework2lark` 安装。Hermes 或其他 Agent 克隆仓库后，把同一目录复制到其用户 skills 根；不要另造一份简化版 Skill。安装后读取新副本的 `SKILL.md`。`lark-cli` 自带与当前版本同步的 `lark-base` 指南；本机没有独立 `lark-base` 目录时，通过 `lark-cli skills read lark-base` 读取，不要求教师再找第二个仓库。

完整收题依赖仓库 FastAPI，所以即使 Agent 已单独安装 Skill，也要保留仓库工作副本，并把其根目录传给 `--repo-root`。

### 2. 只读检查

在仓库根目录运行：

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . check
```

只处理返回的 `nextAction`，完成后重跑。不要把一长串配置问题一次抛给教师：

| `nextAction` | AI 动作 |
|---|---|
| `clone_repository` | 克隆完整仓库并重新定位 `--repo-root` |
| `install_runtime` | 安装 uv、lark-cli 和 API 依赖；执行 `uv sync --directory apps/api --all-groups` 与 `uv run --directory apps/api alembic upgrade head` |
| `install_web` | 仅教师明确需要可视化框题时安装 Node 20+、执行 `npm install` |
| `configure_ocr` | 只询问 PaddleOCR/AI Studio Token，再走安全配置命令 |
| `authorize_lark` | 安装 `@larksuite/cli` 后执行 `lark-cli auth login`，让教师完成一次用户授权 |
| `init_base` | 用内置空白模板创建 Base |
| `disambiguate_base` | 请教师在飞书中给同名库改名；不得取第一个 |
| `repair_base_schema` | 停止写入，依据内置 JSON 契约修复；不得覆盖已有非空教学数据 |
| `start_using` | 进入收题三选一，不再讲安装步骤 |

### 3. 安全配置 OCR

Token 只能通过进程环境或标准输入进入脚本，不能放进命令行参数、聊天回显、日志或仓库。AI 可在自己的安全执行环境临时设置 `PADDLEOCR_ACCESS_TOKEN`，随后运行：

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . configure-runtime
```

默认使用教师手动框题或对话选题，不配置自动检测。教师明确希望整页自动给候选框时，才询问 Yescan 两项密钥并加 `--enable-yescan`；Yescan 不是完成错题学习闭环的前置条件。

如果 Agent 只能使用 stdin，发送以下 JSON，并加 `--stdin-json`：

```json
{"paddleocrAccessToken":"<只在本机进程中提供>"}
```

脚本原子更新被 Git 忽略的根目录 `.env`，输出只说明配置类别，不回显值。

### 4. 创建空白 Base

先完成飞书用户授权，再运行：

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . init-base
```

内置 `homework2lark-empty.base` 负责快速导入；`base-schema.json` 与 `base-views.json` 负责回读验证。模板只有 `错题页面 / 错题题目 / 错题记录 / 变式题`、基础视图和空仪表盘，没有记录、班级名单、固定年级或旧审核字段。

只有教师已经给出当前年级和学期日期时，才同时提供四项参数：

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . init-base --grade 三年级 --term-name 2026学年第一学期 --start-date 2026-09-01 --end-date 2027-01-31
```

这会创建受年级和日期共同约束的教学优先视图。缺任一参数时不创建假定范围。唯一同名正确 Base 返回 `no_change`；多个同名或结构冲突必须停止。

### 5. 最终验证与启动

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . verify
```

返回 `status=ready` 后，首次收题按 `collection-modes.md` 让教师选择 1/2/3。需要 API 时启动：

```powershell
uv run --directory apps/api uvicorn --app-dir src mistake_notebook_api.main:app --port 8000
```

只有需要 Web 手动框题时再运行 `npm run dev:web`。不要要求普通教师运行测试、查看 OpenAPI、理解数据库迁移或手工创建字段。

## 隐私与失败边界

- 不输出 PaddleOCR/Yescan 密钥、飞书 open_id、Base token、表/字段/记录 ID 或教师绝对路径。
- 内置 `.base` 是飞书官方可导入格式，包含该空白模板自身所需的内部结构标识；它不包含用户业务 Base、记录、名单或凭证。公开 JSON 契约不保存远端 ID。
- 不把现有业务 Base 当模板导出，不删除或清洗教师正在使用的 Base。
- 写入失败后先回读，确认是否已经创建成功；不得盲目重复导入。
- PaddleOCR 是默认真实 OCR。测试替身只存在于测试目录，不能成为教师配置选项。
