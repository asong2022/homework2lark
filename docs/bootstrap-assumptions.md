# Bootstrap 假设

## 1. 规则来源与初始化状态

- 仓库根目录没有 `TRELLIS.md`，且仓库尚无 Git 提交；本次无法读取一个不存在的文件。
- 当前可执行的 Trellis 规则源为 `AGENTS.md`、`.trellis/workflow.md`、`.trellis/spec/` 与项目级 `.agents/skills/`。
- `.trellis/` 已完成初始化；公开发行快照只保留项目 Spec，不包含个人开发者身份、任务历史和工作日志。
- 仓库中没有产品代码或技术栈清单。`homework_library_import_template_v2.xlsx` 视为用户已有领域资产，本次不修改、不接入，也不据此扩展导入功能。

## 2. Trellis 采用配置

| 配置项 | 本次采用值 | 落地方式 |
|---|---|---|
| profile | `llm-app` | 写入项目 Spec、任务设计与总结；当前 Trellis 初始化产物没有可验证的 profile 元数据字段 |
| preset | `standard` | 采用标准的 PRD → design → implement → check 工作流 |
| adoption level | `L1 + L2` | L1：持久化项目/编码 Spec；L2：每个复杂变更使用 Trellis 任务与规划工件。暂不启用更高等级的自动编排或治理能力 |
| project type | greenfield | 先建立边界、契约和一条纵向流程，不迁移旧代码 |
| phase | Phase 1 / MVP | 只实现单图、单题、单 Provider、人工审核闭环 |

## 3. 产品假设

- 当前只有一位小学数学教师在本机使用，不建立账号、学生档案、班级、权限或多租户。
- “错题”在初始 Bootstrap 指教师从作业/试卷来源中确认要沉淀的一道题；本地 `MistakeOccurrence` 仍只设计关系、不建表。2026-07-14 后，飞书 Base 增加轻量 `错题记录` 分组投影，同题同类错误的一组学生一行，但仍不建立学生档案或统计系统。
- 教师审核后的 `ReviewedProblem` 是未来复用门槛。OCR 成功不等于审核成功。
- 原图、裁图、OCR 运行、人工修订与审核状态分别持久化；任何后续数据不得覆盖上游证据。
- 所有时间以 UTC 存储、ISO 8601 输出；ID 使用带领域前缀的 UUID 字符串。

## 4. 技术与运行假设

- Web：Next.js App Router、React、TypeScript；不引入大型 UI 框架或全局状态库。
- API：Python 3.11、FastAPI、Pydantic v2、SQLAlchemy 2、Alembic。
- 本地开发数据库为 SQLite；业务代码通过 Repository 边界访问持久化数据。
- 文件存储为仓库内本地目录，通过 `StorageAdapter` 隔离；数据库只保存 storage key，不保存绝对路径或图片二进制。
- 浏览器提交 `normalized_top_left` 坐标（0 到 1）；后端验证后转换并保存为绑定原图尺寸的 `pixel_top_left` 整数坐标。
- 单个上传文件上限默认 15 MiB，只接受经 Pillow 解码确认的 JPG/JPEG/PNG；扩展名和客户端 MIME 不能单独作为可信依据。
- 原始字节保持不变；宽高、服务端裁图和浏览器预览都按 EXIF orientation 后的显示方向解释，避免手机照片的预览坐标与裁图错位。
- API 默认前缀为 `/api/v1`，开发端口为 8000；Web 默认端口为 3000。

## 5. OCR 假设

- 业务层只依赖统一 `OCRProvider` 协议。
- 本地开发与自动化测试默认使用 `FakeOCRProvider`，保证无需模型下载即可验证完整业务流程。
- 真实 Web OCR 优先使用 `PaddleOCRVLAPIProvider`：调用 PaddleOCR/AI Studio 官方托管 Job API，模型为 `PaddleOCR-VL-1.6`，无需本机安装 PaddlePaddle、GPU 或 VLM 权重。
- 托管 Provider 只把教师已确认的题目裁图发往云端；Token 仅从被 Git 忽略的 `.env` 读取，Job 状态和 JSONL 原始结果作为私有机器证据保存。
- `PaddleOCRProvider` 仍保留为 PaddleOCR 3.x 本地推理回退选项，被限制在独立适配器内；它需要可选重型依赖，但不是使用 `PaddleOCR-VL-1.6` 的前置条件。
- OCR 返回空文本时仍保存成功运行及原始响应，题目保持不可复用并提示教师手工填写；Provider 异常或超时则保存失败的 `OCRRun`，原图和区域保持可重试。

## 6. 隐私、删除与日志

- 当前不要求或主动提取学生姓名、班级、学号等身份数据。
- Fake Provider 不向第三方发送图片；本地 PaddleOCR 在本机处理图片。启用 `paddleocr_vl_api` 时，题目裁图会发送给 PaddleOCR/AI Studio 官方云服务，不传本地路径、SourceAsset ID 或教师元数据。
- 日志只能记录请求 ID、实体 ID、Provider 名称、耗时、状态和安全错误码；禁止记录图片二进制、完整 OCR/作答文本或 API Key。
- `StorageAdapter` 提供删除方法用于写入失败补偿；数据库聚合删除和级联关系只完成设计保留，Repository 暂不增加未使用的删除 CRUD。Phase 1 不开放删除 API，避免在没有恢复/确认交互时提供破坏性操作。

## 7. 当前范围解释

- “最小代码骨架”按可真实试用理解：实现这一条纵向流程所需的完整代码、迁移、页面与测试，而不是为 Roadmap 功能创建空模块。
- PDF 只在 `media_type` 与 Roadmap 中保留扩展方向；本阶段上传 API 明确拒绝 PDF。
- `ocr_completed` 表示机器运行已完成但没有可直接送审的非空文本；有非空 OCR 文本或人工修订后进入 `needs_review`；只有人工修订存在时才能进入 `reviewed`。
