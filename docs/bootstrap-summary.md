# Bootstrap Summary

## 1. Trellis 关键规则与差异

- 规则优先级实际来自根目录 `AGENTS.md`、`.trellis/workflow.md`、`.trellis/spec/` 和项目 `.agents/skills/`。
- 用户要求首先完整阅读根目录 `TRELLIS.md`，但仓库中不存在该文件；本次没有虚构其内容。`docs/bootstrap-assumptions.md` 记录了这一差异，并以现有 Trellis 权威文件继续。
- Trellis 要求复杂任务先 PRD/design/implement，再进入实现；本次已经创建并启动 `.trellis/tasks/07-12-upload-select-ocr-review-one-problem/`。
- 实现前读取分层 Spec；实现后执行全量检查并将新发现回写 `.trellis/spec/`；提交前必须向用户展示一次 commit plan 并获得确认。
- 初始化遗留任务 `00-bootstrap-guidelines` 的 notes 标注为 `fullstack project`。本次按用户要求采用 `llm-app` 作为产品/任务 profile；当前 Trellis 元数据没有 profile 字段，因此差异以文档和 Spec 落地，而非伪造初始化元数据。
- 代码目录是 Web/API workspace，但 Trellis Spec 采用 single-repo cross-layer scope，使 `get_context.py --mode packages` 能真实发现 `backend`、`frontend`、`project` 三层规范。

## 2. 实际采用配置

| 项目 | 值 |
|---|---|
| profile | `llm-app`（文档/Spec/任务层） |
| preset | `standard` |
| adoption level | L1 项目 Spec + L2 Trellis 任务工作流 |
| project type | greenfield |
| phase | Phase 1 / MVP |
| current user model | 单教师、本机、无账号 |
| architecture | 模块化单体、一个 Web、一个 API、一个配置中的 OCR Provider |

## 3. 创建的文档

- `docs/bootstrap-assumptions.md`
- `docs/phase-one-prd.md`
- `docs/domain-model.md`
- `docs/data-flow.md`
- `docs/provider-abstraction.md`
- `docs/normalized-problem-record.md`
- `docs/api-contract.md`
- `docs/acceptance-criteria.md`
- `docs/architecture-decision-record.md`
- `docs/roadmap.md`
- `docs/bootstrap-summary.md`
- 根目录 `README.md`
- Trellis 项目/后端/前端/跨层 Spec 和第一条任务的 PRD/design/implement/research/context 工件。

## 4. 创建的主要目录

```text
apps/
  api/       FastAPI、领域/应用/基础设施、Alembic、测试
  web/       Next.js、录入/审核/详情页面、Vitest、Playwright
packages/
  contracts/ OpenAPI 快照
docs/        Phase 1 产品与架构文档
storage/
  sources/   原始文件（运行数据忽略提交）
  crops/     题目裁图（运行数据忽略提交）
data/        SQLite 运行数据
.trellis/
  spec/      L1 项目知识
  tasks/     L2 任务工件
```

## 5. 技术栈

- Frontend：TypeScript 5、React 19、Next.js 16 App Router、原生 Pointer Events、原生 CSS、Vitest/Testing Library、Playwright。
- Backend：Python 3.11、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic、Pillow、Uvicorn、Pytest/Ruff/Mypy。
- Database：SQLite，Repository + Unit of Work；迁移可转向 PostgreSQL，但没有提前实现双数据库基础设施。
- Storage：本地文件系统，path-safe/atomic `LocalFileStorageAdapter`；只向数据库保存 storage key。
- Contract：FastAPI OpenAPI → committed JSON → generated TypeScript；前端在运行时继续校验不可信的 2xx JSON。

## 6. 当前共享端到端流程

```text
AI 对话或 Web 上传 JPG/JPEG/PNG 原图
→ 保存 SourceAsset 与不可变原始字节
→ Web 人工框题 / 对话选择 Yescan 整题候选 / 单题整图录入
→ 校验坐标并创建 ProblemRegion/ReviewedProblem(draft)
→ 保存独立 PNG 裁图
→ 追加 OCRRun 并调用一个 OCRProvider
→ 同屏显示来源、区域、裁图、OCR 原文和 Provider 信息
→ 保存新的 ProblemRevision
→ 显式审核该 revision
→ GET problemId 重建 normalized record
→ 显式发布到飞书 `错题页面/错题题目`
→ Codex/Hermes 以后从 Base 选题、生成编号变式并追加到独立 `变式题` 表
```

原图、机器结果、教师修订和审核事件没有互相覆盖。重复 OCR/修订追加历史；失败 OCR 仍保留 source、region 和 crop。

## 7. OCR Provider

- 测试路径：`FakeOCRProvider`，不访问网络，只用于自动化或显式测试模式。
- Web 真实路径：`PaddleOCRVLAPIProvider`，调用 PaddleOCR/AI Studio 官方托管 Job API 与 `PaddleOCR-VL-1.6`；无需本地 PaddlePaddle、GPU 或 VLM 权重。
- 本机已用用户授权的 `image2.png` 完成真实上传→区域→OCRRun→重新读取链路：Provider/model 为 `paddleocr_vl_api` / `PaddleOCR-VL-1.6`，标准化文本 1853 字符，原图和裁图仍可读；浏览器证据页也显示真实 Provider/模型与非空文本。
- 本地回退：`PaddleOCRProvider` 仍保留为 PaddleOCR 3.x / `PP-OCRv5_server_rec` 选项，与 `PaddleOCR-VL-1.6` 托管 API 是两条不同路径。
- Quark Yescan 已作为整页题目检测 Provider 接入，对 group-level `StructureInfo` 一题一候选；MinerU/PDF 和 Doc2X 尚未正式接入，也未实现多 Provider 路由、降级或投票。

## 8. 已完成验证

- Backend：Ruff format/check、Mypy 通过；Pytest 99 项通过，新增托管 Job API multipart、状态轮询、Markdown 标准化、超时/错误映射、HTTPS 与 Token 脱敏合约。
- Frontend：ESLint、TypeScript；Vitest 39 项通过。
- Build：Next.js production build 通过。
- E2E：Playwright Chromium 3 条通过；另完成一次真实托管 OCR 的浏览器只读验证。
- Skill：19 项单元测试与 UTF-8 quick validation 通过；真实 Base schema-check 通过。
- Contract：OpenAPI 快照与生成 TypeScript 同步，错误响应公开 `ErrorEnvelope`。
- Migration：SQLite fresh upgrade/downgrade/upgrade 测试通过。

## 9. 尚未实现

初始 Bootstrap 没有实现学生/班级/账号、统计看板、PDF/MinerU、多 Provider 自动路由、图像增强、去手写、错因 AI、讲题、图形型变式、每日一练 Word/PDF、RAG/向量/知识图谱、队列、微服务、多教师协作、权限和消息通知。后续于 2026-07-14 仅在飞书 Base 增加 `错题记录` 轻量分组投影；本地原子级 `MistakeOccurrence`、学生表、账号和班级统计仍未实现。

## 10. 已记录架构假设

- 当前单教师/单进程，不对并发 revision number 或多用户冲突作虚假保证。
- 浏览器提交 normalized bbox，服务端保存 EXIF 显示平面的 pixel bbox；裁图由后端生成。
- `ocr` 是教师当前修订的机器基线，`latestOcrRun` 是最新尝试，二者不能混淆。
- OCR 同步 SDK 通过有截止时间的 daemon worker 调用；截止时间终结 HTTP/数据库 run，但不声称能取消底层原生推理。
- Windows 中文仓库路径下使用 uv `package = false`，通过显式 `src` 导入入口避免 editable `.pth` 代码页故障。
- Phase 1 不开放删除 API；Storage 删除只用于当前写入失败补偿，聚合删除另立任务。

## 11. 风险

- 托管 PaddleOCR-VL 的风险是外网/配额/Token 可用性与题目裁图云端传输；表格、公式和图文结果仍必须对照原裁图由教师核对。
- SQLite 和单进程线程截止方案只适合当前个人 MVP；协作/高并发阶段需 PostgreSQL、并发控制和可取消任务重新设计。
- 作业图片仍可能包含个人信息；教师试用前应选择匿名样例，未来托管 Provider 必须新增数据传输披露和删除流程。
- `npm audit` 当前报告 Next.js 间接固定的 PostCSS 两项 moderate advisory；本 MVP 不接收或动态生成 CSS，未使用破坏性降级修复。升级到上游修复版本后需重新审计。

## 12. 下一条建议任务

下一条建议任务是按教师的 Agent-first 理念完善 `shi-homework2lark` 技能组：对话接收图片/PDF/Word → OCR/视觉整题提取 → 教师选题与补充真实作答 → AI 整理并确认 → 发布 Base → 生成变式/再练与必要题图 → 再练反馈回到可追溯记录。这个任务优先重用现有 API、Base 与专用绘图 Skill，不把 LLM 锁死在后端。
