# Phase 1 Acceptance Criteria

## AC-001 合法图片上传

**Given** 教师选择可解码且未超过限制的 JPG/JPEG/PNG，**When** 上传，**Then** API 返回 201、公共 asset ID、显示尺寸、hash、MIME 和 content URL。

## AC-002 原始文件不可变

**Given** SourceAsset 已保存，**When** 完成裁图、OCR、修订和发布，**Then** 原图 bytes、storage key 与 SHA-256 不变，crop 使用独立 key。

## AC-003 人工框题与上下文恢复

**Given** 已上传服务器图片，**When** 教师框选、保存并重新打开 `/intake/{assetId}`，**Then** 持久化题框以只读叠加恢复，教师可以继续补框，已有 public problem IDs 不丢失。

## AC-004 坐标验证与裁图

**Given** 合法 normalized bbox，**When** 创建 region，**Then** 后端转换为绑定 EXIF 显示尺寸的 pixel bbox 并生成正确 PNG crop；越界、非有限或过小请求失败且 source 保留。

## AC-005 生产 OCR 配置

**Given** 默认配置，**When** API 组合 OCR Provider，**Then** 使用 `paddleocr_vl_api` / `PaddleOCR-VL-1.6`；生产配置不接受 `fake`，缺 Token 返回明确配置错误。

普通测试使用测试目录内注入的 stub 和可注入 HTTP transport；它们不进入生产包或教师配置。真实云端测试只在显式授权环境下运行。

## AC-006 OCR 运行持久化

**Given** 一次 OCR 请求，**When** 成功、失败或超时，**Then** 保存 Provider、model/version、raw response 或安全错误、标准文本、blocks、状态和时间；source/region/crop 保留。

## AC-007 人工修订立即成为当前版本

**Given** 属于同一区域的 OCR run 和非空教师确认文本，**When** 保存，**Then** 新增递增 `ProblemRevision` 并立即更新 `ProblemAsset.current_revision_id`，无需第二次审核调用。

## AC-008 修订不覆盖 OCR

**Given** OCR 文本与教师修订不同，**When** 保存修订，**Then** OCRRun 的文本和 raw response 逐值不变。

## AC-009 重复 OCR 与修订追加历史

**Given** 已有 OCRRun/revision，**When** 重试 OCR 或再次保存修订，**Then** 创建新 run/version，旧记录和当前修订依据不被覆盖。

## AC-010 无当前修订拒绝发布

**Given** `ProblemAsset.current_revision_id` 为空或指向无效/空修订，**When** 发布，**Then** 返回 409 `problem_not_publishable`，不写飞书。

## AC-011 有效当前修订可以发布

**Given** 当前修订非空且 source、region、crop、OCR 依据完整，**When** 明确发布，**Then** 创建或更新同一 `ProblemPublication` 并按稳定 ID 幂等同步飞书，不读取审核状态或审核时间。

## AC-012 problemId 完整重读

**Given** 已完成 OCR 和修订，**When** 按 problemId 读取，**Then** 返回 source、region、选定/最新 OCR、当前修订、全部 OCR/修订历史、publication 与 lineage；不返回 `status/review/reviewedAt/statusHistory/futureReuseEligible`。

## AC-013 数据迁移保全

**Given** 0004 数据库已包含 source、region、OCR、revision、旧题目聚合和 publication，**When** 升级 0005，**Then** 业务记录数量、公开 problem ID、当前修订和发布远端指针保持不变，旧审核表退出运行时 Schema。

## AC-014 飞书字段收敛

**Given** 发布到现有 Base，**When** 生成 payload，**Then** 写入 `系统题目ID` 与 `本地修订版本`，不要求或写入 `已审核时间/审核状态/是否待复核`。

## AC-015 OCR 失败可恢复

**Given** Provider 不可用或超时，**When** OCR 失败，**Then** 失败 run 持久化并返回稳定中文错误；再次调用只追加新 run，不要求重新上传或框题。

## AC-016 自动化质量门

**Given** 新检出仓库及已安装依赖，**When** 执行项目检查，**Then** 后端 Ruff/format/mypy/pytest、Alembic、前端 ESLint/tsc/Vitest/build/Playwright、OpenAPI 合约和 Skill 全量测试全部通过。

## AC-017 隐私与日志

**Given** 任意成功或失败路径，**When** 检查日志和错误响应，**Then** 不含完整图片、OCR/修订/学生文本、Token、CLI stderr、SQL 参数或绝对私有路径。

## 补充质量标准

- Provider raw NumPy 值必须可 JSON 序列化。
- 文件/数据库补偿只删除本次失败步骤写入的文件，不删除既有 source/crop。
- FastAPI OpenAPI、提交的快照和生成 TypeScript 类型保持一致。
- Web 只承担上传与框题，不调用 OCR、修订或发布。
