# Phase 1 Acceptance Criteria

## AC-001 合法图片上传

**Given** 教师选择一张可解码的 JPG、JPEG 或 PNG 且未超过限制，**When** 上传，**Then** API 返回 201、公共 asset ID、显示宽高、hash、大小、MIME 和 content URL。

证据：API 参数化集成测试（3 种扩展/2 种实际格式）与 Playwright PNG 流程。

## AC-002 原始文件不可变

**Given** SourceAsset 已保存，**When** 完成裁图、OCR、修订和审核，**Then** 原图 storage key 与 SHA-256 未变化，crop 使用不同 key。

证据：完整流程前后读取 bytes/hash 断言。

## AC-003 手动框选

**Given** 已上传服务器图片，**When** 教师正向或反向拖出矩形，**Then** UI 显示归一化区域摘要并允许确认；极小/零面积区域不可提交。

证据：`ImageRegionSelector` 组件测试 + Playwright drag。

## AC-004 坐标验证与裁图

**Given** 合法 normalized bbox，**When** 创建 region，**Then** 后端转换为绑定 EXIF 显示尺寸的 pixel bbox，生成尺寸正确的 PNG crop；越界/非有限/过小请求返回 422 且 source 保留。

证据：坐标单元测试、EXIF/裁图集成测试。

## AC-005 统一 Provider

**Given** 应用配置一个 `OCRProvider`，**When** 识别 region，**Then** application 只消费统一 `OCRResult`，Fake 与 Paddle adapter 通过同一合约测试。

证据：Provider contract tests；Paddle 使用模拟 3.x raw result，不要求真实模型。

## AC-006 OCR 运行持久化

**Given** 一次 OCR 请求，**When** 完成，**Then** 保存 Provider、model/version、raw response、normalized text、blocks/confidence、状态、错误码和起止/耗时。

证据：Repository/API 集成断言。

## AC-007 审核证据同屏

**Given** OCR 已完成，**When** 打开审核页，**Then** 同时可见原图区域、crop、OCR 原文、Provider/model 和当前审核状态。

证据：组件测试 + Playwright role/text 断言。

## AC-008 人工修订新版本

**Given** 成功 OCR run 和非空修订文本，**When** 保存，**Then** 创建 revision number 1（或下一号），设为 current，状态为 `needs_review`。

证据：领域/API 测试。

## AC-009 修订不覆盖 OCR

**Given** OCR 文本与教师修订不同，**When** 保存修订，**Then** OCRRun.extracted_text/raw response 保持逐值不变。

证据：数据库前后快照。

## AC-010 标记 reviewed

**Given** 有效 current revision，**When** 教师确认该 revision，**Then** status 为 `reviewed`、记录 reviewedAt/status event，并返回完整记录。

证据：领域/API/Playwright。

## AC-011 无人工版本拒绝审核

**Given** 没有有效 revision，**When** 审核，**Then** 返回 409 `review_revision_required` 且状态不变。

证据：领域/API 回归测试。

## AC-012 未来复用资格

**Given** 任意问题状态，**When** 读取，**Then** `futureReuseEligible` 只在 reviewed + 有效 current revision 时为 true；新保存修订后立即变 false，直至重新审核。

证据：状态机参数化单元测试。

## AC-013 problemId 完整重读

**Given** 完成流程，**When** 新请求按 problemId 读取，**Then** 返回 source/content URL、region/crop URL、OCR 原始/标准结果、current revision、全部版本历史、审核状态历史与 lineage。

证据：严格 schema API 集成测试 + Playwright 页面 reload。

## AC-014 OCR 失败可恢复

**Given** Provider 不可用或超时，**When** OCR 失败，**Then** 失败 run 持久化，source/region/crop 可读，UI 显示明确可重试错误；重试只创建新 OCR run。

证据：注入 failing/timeout Fake 的 API/组件测试。

## AC-015 重复 OCR 不覆盖

**Given** region 已有 OCRRun，**When** 再次识别，**Then** 新 run ID 被追加，先前 terminal run 不变；对已审核题单独重试不撤销审核。

证据：数据库计数、历史值和状态断言。

## AC-016 重复人工修改不覆盖

**Given** 已有 revision 1，**When** 保存修改，**Then** 创建 revision 2、revision 1 保留；若原题 reviewed，则转 needs_review、清 reviewedAt、追加带 revision ID 的状态事件。

证据：领域/API 参数化测试。

## AC-017 自动化覆盖

**Given** 新检出仓库及已安装依赖，**When** 执行项目检查，**Then** 后端 Ruff/format/mypy/pytest、前端 ESLint/tsc/Vitest/build、OpenAPI 合约检查及一条 Playwright full flow 全部通过。

证据：实际命令退出码和测试报告。

## AC-018 README 可复现

**Given** Windows PowerShell、Node >=20.9、uv 与 Python 3.11，**When** 按 README 执行，**Then** 能同步依赖、迁移数据库、配置 Fake/Paddle、启动 API/Web 并运行测试。

证据：命令 smoke check；真实 Paddle 识别为独立、环境门控的手工验证。

## AC-019 来源页批量审核与上下文恢复

**Given** 同一来源页已保存两道以上错题，**When** 教师打开本页批量审核并一次确认，**Then** 所有有效题目分别追加 revision/review；单题失败不回滚其他题。返回录入后仍显示同一原图、持久化题框和审核状态。

证据：来源页集合 API 集成测试、批量组件部分失败测试和 Playwright 返回恢复流程。

## AC-020 OCR 状态可解释

**Given** 题目可能没有运行、运行失败、成功但为空、或历史成功后最新重试失败，**When** 教师查看录入/审核，**Then** 四种状态使用不同中文说明和恢复动作，且既有成功 OCR 基线不会被最新失败遮蔽。

证据：OCR 证据面板单元测试与真实 PaddleOCR 非空 smoke。

## AC-021 教师中文帮助

**Given** 普通小学数学教师不理解 Swagger，**When** 打开 Web，**Then** 可从常驻导航进入中文帮助并完成上传、框题、批量审核和失败恢复；`/docs` 明确只供 AI/开发者配置与诊断。

## 补充质量标准

- 非法/损坏/超大文件均不产生可用 asset。
- 状态事件包含关联 OCR/revision ID，能解释变化来源。
- Provider raw NumPy 值可 JSON 序列化。
- 日志断言不含完整 OCR/corrected text、图片或密钥。
- 文件/数据库补偿测试不会删除既有 source/crop。
- OpenAPI 快照和生成 TypeScript 类型无漂移。
