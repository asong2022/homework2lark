# AI 安装执行单

你正在为一位小学数学教师安装 `homework2lark`。教师要的是“配置好后直接发作业”，不是一份开发教程。

## 最终结果

直到以下条件全部成立才算完成：

1. 完整仓库已克隆到教师本机；
2. `.agents/skills/shi-homework2lark` 已安装到当前 Agent 可发现的用户 skills 根；
3. API 的 Python 3.11/3.12 环境和数据库迁移已完成；
4. PaddleOCR-VL-1.6 Token 已安全写入被 Git 忽略的 `.env`；
5. `lark-cli` 已用教师自己的飞书用户身份授权；
6. 内置空白模板已创建或幂等复用唯一正确的飞书 Base；
7. `onboarding.py verify` 返回 `status=ready`；
8. 告诉教师：“可以开始发作业图片、PDF 或 Word 了。”

## 1. 获取仓库

公开仓库：

```text
https://github.com/asong2022/homework2lark
```

如果当前目录不是完整仓库，克隆它。保留仓库工作副本：首次从图片/PDF 收题需要其中的 FastAPI，本 Skill 不是一个脱离运行时的提示词文件。

## 2. 安装唯一入口 Skill

Codex 应调用内置 `skill-installer`：

```text
repo = asong2022/homework2lark
path = .agents/skills/shi-homework2lark
ref = main
```

不要覆盖已经存在的目录；先检查版本，再由用户允许升级或使用新的临时目录验证。安装后在下一轮读取已安装副本的 `SKILL.md`。

Hermes/其他 Agent 把仓库中的 `.agents/skills/shi-homework2lark` 整目录复制到其用户 skills 根，必须保留 `agents/`、`evals/`、`references/`、`scripts/`、`templates/`、`tests/` 和 `bundle.json`。不要只复制 `SKILL.md`。

## 3. 安装最小运行时

需要：

- Python 3.11 或 3.12（可由 uv 管理）；
- [uv](https://docs.astral.sh/uv/)；
- Node/npm 仅用于安装 `lark-cli`，以及教师明确使用 Web 时的前端；
- `lark-cli`：`npm install -g @larksuite/cli`。

在仓库根目录执行：

```powershell
uv sync --directory apps/api --all-groups
uv run --directory apps/api alembic upgrade head
```

不要默认安装本地 PaddlePaddle。官方托管 PaddleOCR-VL-1.6 不需要本地模型和 GPU。

`lark-cli` 内置与其版本同步的 `lark-base` Agent 指南。文件系统没有独立 `lark-base` Skill 时，使用：

```powershell
lark-cli skills read lark-base
```

按它要求继续读取相关 reference；不要凭记忆拼飞书参数。

## 4. 用状态机逐步配置

运行：

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . check
```

一次只处理返回的 `nextAction`，不要一次询问多项：

- `install_runtime`：补齐上述运行时；
- `configure_ocr`：只询问 PaddleOCR / AI Studio Token；
- `authorize_lark`：运行 `lark-cli auth login`，让教师完成一次用户授权；
- `init_base`：运行内置模板初始化；
- `disambiguate_base`：让教师给同名 Base 改名，不得取第一个；
- `repair_base_schema`：停止写入，依据模板契约修复，不覆盖非空教学数据；
- `start_using`：安装结束，进入收题。

### 安全写入 OCR 配置

密钥不能进入 argv、聊天回显、日志、源码或 Git。优先把 Token 临时放进当前进程环境：

```powershell
$env:PADDLEOCR_ACCESS_TOKEN='<仅在本机安全输入>'
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . configure-runtime
Remove-Item Env:PADDLEOCR_ACCESS_TOKEN
```

也可以把以下对象通过 stdin 传给 `--stdin-json`，但不得打印真实值：

```json
{"paddleocrAccessToken":"<secret>"}
```

默认 `REGION_DETECTION_PROVIDER=manual`。只有教师明确希望整页自动产生候选框时，才询问 Yescan Key ID/Key，并使用 `--enable-yescan`。Yescan 不是必配项。

### 飞书授权与建库

```powershell
lark-cli auth status --json --verify
lark-cli auth login
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . init-base
```

如果教师已经给出年级、学期名称和起止日期，可以一次创建有范围的教学优先视图：

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . init-base --grade 三年级 --term-name 2026学年第一学期 --start-date 2026-09-01 --end-date 2027-01-31
```

四项必须同时存在。没有范围时不创建假定视图。

## 5. 验证并交付

```powershell
python -X utf8 .agents/skills/shi-homework2lark/scripts/onboarding.py --repo-root . verify
```

必须看到 `status=ready`。然后：

- 需要收题时启动 API：

  ```powershell
  uv run --directory apps/api uvicorn --app-dir src mistake_notebook_api.main:app --port 8000
  ```

- 只有教师要求可视化手动框题时，才执行 `npm install`、`npm run dev:web`；
- 第一次收题读取 `collection-modes.md`，让教师选择 1/2/3，不能由 AI 自动决定。

## 绝对不要做

- 不要求教师手工创建四张表或逐字段配置；
- 不把现有业务 Base 直接导出为公开模板；
- 不输出 PaddleOCR/Yescan 密钥、飞书 open_id、Base token、表/字段/记录 ID、绝对私有路径；
- 不把测试替身当成可选 OCR、自动框题或发布模式；
- 不因 Web 没启动而阻塞纯对话收题、变式或练习；
- 不运行公开 CI 的真实云端测试，除非用户明确授权并已安全提供凭据。
