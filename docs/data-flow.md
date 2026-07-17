# Phase 1 数据流

## 1. 总体原则

- 每一步只消费上一步的稳定 ID 和明确契约。
- 已经持久化的上游证据不会因下游失败被删除。
- 文件字节进入 Storage，关系/元数据进入 Database，前端只持有临时选择和公共 ID。
- API 对外使用 camelCase；数据库使用 snake_case；映射由后端 schema/assembler 负责。

## 2. 上传流程

```text
Teacher
→ Frontend file input
→ POST /api/v1/assets (multipart)
→ size + decode + format validation
→ SHA-256 + EXIF-oriented display metadata
→ StorageAdapter.write(source key, original bytes)
→ SourceAsset repository
→ commit metadata
→ assetId + contentUrl
```

边界：客户端 filename/MIME 仅作提示；Pillow 实际解码决定是否接受。原始字节不改写，但预览尺寸和后端裁图都使用 `ImageOps.exif_transpose` 后的显示方向。数据库失败时删除本次新写入的 source key。

Skill 有三个入口，但上传后共用同一个 `SourceAsset`：

- `web`：上传一次后打开 `/intake/{assetId}`，不再上传、不调用自动检测，教师直接手动框一道或多道错题。
- `chat`：上传后调用一次已配置的 Yescan 题目检测，在对话里展示整题候选，由教师选择。
- `single`：教师直接给出一题一图，以整图作为一道题，不调用检测。

## 3. 人工框题与可选自动候选流程

```text
SourceAsset
→ default Web path: teacher draws/moves/resizes/deletes one or more manual boxes
  OR optional chat/compatibility path:
     POST /api/v1/assets/{assetId}/detection-runs
     → configured detection Provider
     → persist private raw evidence + immutable RegionCandidates
     → teacher selects candidates; optional “合并为一题” corrects Provider split boxes
→ POST /api/v1/assets/{assetId}/regions/batch
→ finite/range/min-size + same-asset + candidate-reuse validation
→ read immutable source bytes
→ floor(left/top), ceil(right/bottom)
→ canonical pixel_top_left bbox
→ server-side PNG crop
→ StorageAdapter.write(one crop per selected logical problem)
→ ProblemRegion + candidate-source links + ProblemAsset
→ commit
→ return ordered public problem IDs
```

前端人工框题是 Web 主线，自动检测不是必经步骤。Yescan Adapter 只在 chat/兼容入口使用：它对每个 group-level `StructureInfo` 一对一创建候选，不会把题内 `Detail` 文字、公式、表格或插图再次拆题，也不会在本地跨框猜测合并。Provider 偶发误切时才由教师显式调整或合并。坐标转换只由后端实现；裁图和原图分别保存。

## 4. OCR 流程

```text
ProblemRegion
→ Web/Skill 对每个已保存题目分别调用 OCR API（按顺序，局部失败不撤销其他题）
→ create OCRRun(running) and commit attempt
→ StorageAdapter.read(crop)
→ configured OCRProvider.recognize(OCRInput)
→ if paddleocr_vl_api: multipart crop → official Job API → authenticated polling → unauthenticated HTTPS JSONL download
→ Provider raw result
→ adapter normalization (Markdown/text, blocks, confidence, JSON-safe raw)
→ finish OCRRun(succeeded)
→ return 201 OCR run
```

异常路径：Adapter 映射安全错误分类，完成同一 OCRRun 为 `failed`，按原因返回 502/503/504。业务层有总截止时间，托管 Adapter 内的轮询截止时间略短；超时或远端 Job 失败不影响原图、区域、裁图或当前人工修订，教师重试时追加新 OCRRun。

托管隐私边界：仅题目裁图和固定模型/处理选项发往 PaddleOCR/AI Studio；不发本地路径、SourceAsset ID、教师元数据或学生身份字段。Token 只用于 Job 提交/查询，不转发给结果 URL，不进入日志或 raw response。

## 5. 人工修订流程

```text
OCRRun(succeeded)
→ Teacher edits text
→ POST /api/v1/regions/{regionId}/revisions
→ validate run belongs to region + correctedText non-empty
→ calculate next revisionNumber
→ create ProblemRevision
→ ProblemAsset.current_revision_id = new revisionId
→ ProblemAsset.updated_at = UTC now
→ commit
```

旧 OCRRun 和旧 Revision 始终保留。新修订保存成功后立即成为当前版本，不再执行第二次审核命令。

## 6. 当前修订门

```text
SourceAsset + ProblemRegion + successful OCRRun
→ Teacher confirms complete corrected content
→ POST /api/v1/regions/{regionId}/revisions
→ current revision becomes available immediately
→ publication may proceed when source/crop/OCR lineage is complete
```

没有有效当前修订时发布返回 `problem_not_publishable`。教师确认仍是内容质量门，但它通过保存修订表达，不再生成状态字段、审核时间或状态事件。

## 7. 读取流程

```text
GET /api/v1/problems/{problemId}
→ Repository loads problem + region + source + OCR runs + revisions + publication
→ assembler selects current revision and its OCR baseline
→ emit NormalizedProblemRecord
→ Agent renders source/crop, machine text, current human text and lineage
```

原图和裁图分别通过受控内容端点读取，不把绝对路径或 base64 放入规范化 JSON。

Web 重新打开 `/intake/{assetId}` 时读取 SourceAsset 和来源页题目集合，把持久化像素 bbox 投影为只读叠加框；只有教师显式点击“继续为本页补框”才进入新的手动框选状态。Web 在返回 public problem IDs 后结束，不承担 OCR、修订或发布。

## 8. 发布到飞书 Base

```text
ProblemAsset(current revision present)
→ Teacher/Agent explicitly requests 发布到飞书
→ POST /api/v1/problems/{problemId}/publications/lark
→ persist ProblemPublication(pending)
→ read immutable source page + crop
→ ProblemPublisher
→ resolve 错题页面 / 错题题目（迁移期兼容 pages/questions）
→ page exact lookup 系统页面ID, then 源文件哈希
→ one physical source page = one 错题页面 row; multiple questions link to it
→ question exact lookup 系统题目ID
→ keep existing readable 页面名称/题目名称, or create a safe 待整理… title for later AI enrichment
→ patch only publisher-owned fields
→ upload only missing source/crop attachments
→ persist succeeded remote record IDs, or failed safe error code
→ normalized record exposes publication state
```

发布失败不改变当前修订、原图、裁图或 OCR。`lark-cli` 重试必须先按系统页面 ID 查找，未找到时再按源文件 SHA-256 查找；唯一哈希匹配直接复用页面，多条匹配安全失败。附件上传是追加语义，单元格已有不可变附件时跳过，避免重复。

Base 是教师与 Agent 的整理、筛选、变式和组卷中转核心，但不保存 OCR raw 或本地修订历史的唯一副本。教师常用视图显示可读的 `页面名称`/`题目名称`，稳定键保存在隐藏的 `系统页面ID`、`源文件哈希`、`系统题目ID`。`错题页面.页码` 与 `错题页面.错题来源` 是唯一事实来源，`错题题目` 的同名字段通过 `所属错题页面` 查找引用。`题干文本` 包含文字选项，`题干图片` 保存非文本视觉，`图片题目` 保留完整裁图。发布端只更新本地证据拥有的字段，不清空教师在 Base 补充的单元、课题、题型、知识点、答案或已有变式。

发布后的 Agent 目录整理是默认闭环的一部分：

```text
Teacher sends image / single-question crop / student-work description
→ Agent presents source evidence, corrected stem and proposed metadata
→ teacher explicitly confirms
→ metadata preview exposes field names only
→ apply fills empty cells or accepts identical values
→ conflicting non-empty teacher content blocks the whole write
→ read back question and linked page
```

目录整理不写学情证据。`错题题目.典型错例` 与 `错题题目.错误表现` 由后续教师确认的 `错题记录` 自动查找引用；没有真实作答分组时保持空白，不用 AI 模拟内容兜底。

## 9. 空白模板与同版已批改作业

```text
Blank PDF/page
→ local page render
→ at most one Yescan AI Agent scene=question-ocr call per blank page
→ AI/teacher aligns structured text with the visual page and confirms complete question regions once
→ corrected pages register to the blank template
→ inspect handwriting + red-mark semantics + mathematical correctness
→ record observed real responses
→ infer causes and group students
```

`question-ocr` 没有可靠 bbox 时只提供结构化题目文本，区域由 AI 对照空白页或教师一次性确认，不能伪造坐标。同版学生卷不重复 OCR 印刷题干。红笔存在不等于答错；勾、叉、划线、圈和作答必须结合数学正确性解释。

身份优先用教师名单核对“学号 + 姓名”，Base 只写姓名。没有名单时 AI 看图结果是私有临时映射，低置信项等待以后校验；如需云端辅助，只把带页序号的姓名/学号小裁图排成少量可读高清联系表。

## 10. 同题同错因学生分组

```text
教师确认修订并已发布的错题题目
→ Teacher provides corrected-work pages / student labels / observations
→ Agent records one/few group-level 典型错例 from real responses first
→ Agent proposes groups and 错误原因 from the observed evidence
→ each proposal shows 对应题目 + 题干图片引用 + 典型错例 + 错因建议
   + 本组人数 + 对应学生多选 + 证据来源
→ Teacher confirms or edits each group
→ create one 错题记录 row per confirmed error group
→ link exactly one 对应错题
→ read back 本组人数 == unique(对应学生)
→ Base lookup projects all 典型错例 / 错误表现 to 错题题目
→ writer projects unique error students, cause-and-count summary, sample size, rate and high-frequency status
→ 错题题目 reverse 学生错题记录 exposes all groups
```

一行不是一个学生，而是同题、同日期、同错因的一组学生。`典型错例` 保存该组一到几个真实作答，不含姓名；`题干图片` 只读引用原题，不复制附件。`对应学生` 可以使用姓名、简称或匿名代号；个人错题集由 Base 多选筛选得到。候选未确认时不写 Base，也不把学生名单写入证据文本。题目表的 `典型错例`、`错误表现` 是只读 lookup，`错误原因` 是带各组人数的文本汇总。人数列显示整数；错误率底层保存 `0～1` 比例、Base 显示一位小数百分比。批改批次的高频规则是 `去重错误人数 / 样本人数 > 35%`；人工/Web 收集没有样本时不伪造错误率，可标记为教师判断。

## 11. Base 举一反三 Skill

```text
Teacher chooses an original from `待生成变式` (`关联变式题` empty)
→ Codex/Hermes runs shi-homework2lark list-selected
→ read teacher-confirmed original text + crop context + questionStemImageCount
  + grouped 典型错例 / 错误表现 / 错误原因汇总
→ fill the 题生变式事实卡: 年级 / 数学本质 / 教师意图 / 再练反馈
→ Agent independently solves the original and designs 1～5 numbered variants
→ default three-item set uses at least two substantive variation axes
→ each item passes math / condition / answer / grade / difficulty / data checks
→ text-only original defaults to text-only variants
→ when a variant still needs or intentionally introduces a diagram, invoke wumu-jihe-html
  and inspect editable HTML + exported PNG
→ deterministic payload validation
→ teacher-visible preview (no Base mutation)
→ explicit write confirmation
→ variant_catalog batch-creates one linked 变式题 row per item
→ each row saves 题干文本 + optional 答案解析 + required 设计意图
→ 核心素养 is read-only lookup from the original
→ declared diagram must exist before write
→ dedicated attachment command uploads each checked PNG and reads it back
→ available variants become eligible for assembly
```

题目与答案解析分列保存，但题目是必需资产，答案解析是可选教师辅助；设计意图是每道变式的必填教学信息。`questionImageCount` 表示完整题目裁图，`questionStemImageCount` 才表示题内非文本视觉；Agent 不得把前者当成配图依据。文本原题默认生成纯文本变式，原题含图也只在新题仍依赖视觉条件时配图；教师明确要求改变表征时可以例外。题图直接附在同一道变式记录，不再维护题图说明或变式复核列。生成统一称为变式题，不建立固定“巩固/拓展/提升/挑战”枚举。教师确认的当前修订是进入 Base 的内容门；未通过数学或图文检查的内容不写回。

典型错例只用于帮助 Agent 针对错误表现设计变式；`【AI模拟典型错例】` 不能当作真实学情证据，也不能在输出中改写成“学生实际这样做过”。

顺序不可颠倒：原错题必须先经教师确认修订并发布到 `错题题目`，Agent 再从 Base 选题生成；每道变式题写入独立的 `变式题` 行，并通过 `来源错题` 关联唯一原题。答案解析与题干分列但可空，不再向原题行追加 `变式题1～5` 新内容。

脚本写回前按实时 schema 解析唯一 Base，写回后逐项核对每条变式的稳定键、来源关系、题干、可选答案与题图状态，确保原题文本、图片、学情和页面关系未被改写。相同原题与规范化题干生成同一 `系统变式ID`，原样重跑复用既有行；新内容只追加，不静默覆盖旧变式。

### 学生个人精准练习

```text
Teacher provides private roster + student number + target count
→ Skill resolves one roster-verified name
→ read-only Base filter: 错题记录.对应学生 contains that name
→ aggregate mistake groups by source question
→ exclude mastered by default
→ prioritize 需再练 / recent evidence / error-category coverage
→ select each original once
→ fill remaining capacity with related available variants only
→ freeze private personal-practice-v2 flat-item manifest + selection report
→ let Word auto-flow complete question blocks without estimated hard page breaks
→ download only selected stem images
→ render M月D日个人练习纸 with prefilled name/student number
```

该流程不新增学生表、不把学号写入 Base，也不以无关题凑数。个人页面识别码使用匿名 `Sxxx`，姓名和学号映射仅保存在教师私有 manifest。已支持整班批量生成；批改扫描由 Agent/`shi-ocr` 观察页面码、题号、作答和批改痕迹，`retry_batch.py` 再确定性定位来源、追加幂等事件并准备 Base 当前投影。一次正确默认只进入“练习中”。

### 用户选择的收集方式

```text
没有明确选择 → 只显示 1 教师精选 / 2 匿名批改统计 / 3 实名绑定统计 → 等待
用户选择 → workflow.py 固化 decidedBy=user → 才读取材料并进入相应流程
```

AI 不得根据材料替用户选模式。匿名方式不做身份映射；实名方式只使用教师私有名单核对，Base 默认只写姓名。

### 再练回收

```text
批改图片/PDF
→ AI/OCR 观察 pageCode、可见题号、真实作答、红笔证据
→ retry_batch.py 映射 pageCode + 题号 → Rxx → questionId/variantId
→ 只读反馈计划与异常隔离
→ append-only 本地事件
→ 已授权的 Base 当前投影与回读
```

`correct` 默认投影为“练习中”，`partial/incorrect` 为“需再练”，`uncertain/not_observed` 不自动改变掌握状态。

### 匿名再练反馈

```text
Teacher describes observed retry response + teacher judgment
→ Agent prepares timezone-aware feedback JSON
→ validate + preview, no mutation
→ teacher explicitly confirms
→ append deterministic event ID to local JSONL (no student identity)
→ patch Base 掌握状态 / 最近再练时间，或实名错误组的再练反馈
→ read back feedback fields and verify all other fields unchanged
→ later variant generation may use the latest unresolved relation
```

本地 JSONL 保存完整重复再练事件；Base 只保留当前状态和组级教师摘要。分组级 `典型错例` 和题目级只读 lookup 不被再练反馈覆盖。相同事件重试不会追加第二行；若本地追加成功而 Base 暂时失败，可按同一 event ID 重试投影。

## 12. 失败场景

| 场景 | API 行为 | 必须保留 | 可重试/恢复 |
|---|---|---|---|
| 文件存储写入失败 | 500 `storage_unavailable` | 无既有数据变化；数据库失败会补偿本次新文件 | 修复存储后重新上传 |
| 文件过大 | 413 `asset_too_large` | 无资产 | 换小文件 |
| 格式错误/伪装扩展名 | 415 `unsupported_image` | 无资产 | 使用合法 JPG/PNG |
| 图片损坏 | 422 `invalid_image` | 无资产 | 重新导出图片 |
| 框选越界/非有限/过小 | 422 `invalid_region` | SourceAsset | 重新框选 |
| 裁图存储写入失败 | 500 `storage_unavailable` | SourceAsset；不删除既有原图 | 修复存储后重新框选 |
| Provider 未安装/不可用 | 503 `ocr_provider_unavailable` | SourceAsset、Region、crop、失败 OCRRun | 重试或修复配置 |
| 托管 PaddleOCR Token 缺失/无效 | 503 `ocr_provider_configuration_error` | SourceAsset、Region、crop、失败 OCRRun | 修复本机 `.env` 并重启 API |
| OCR 超时 | 504 `ocr_timeout` | 同上 | 显式重试，创建新 run |
| OCR 空文本 | 201 + warning | 完整 OCRRun/raw | 教师手工填修订或重试 |
| 修订保存失败 | 4xx/500 稳定错误 | Source、Region、全部 OCR/旧修订 | 修正输入/重试 |
| 缺少有效当前修订 | 409 `problem_not_publishable` | 全部本地证据 | 先保存教师确认修订 |
| 飞书不可用/超时 | 503 `lark_publisher_unavailable` | 当前修订和失败发布记录 | 显式重试同一稳定 ID |
| 飞书字段/登录配置错误 | 503 `lark_publisher_configuration_error` | 同上 | 修复 lark-cli 登录或 Base schema |
| 飞书存在重复稳定 ID | 502 `lark_publisher_invalid_response` | 同上；不猜测目标行 | 人工清理重复远端行后重试 |
| 飞书主字段缺少 `页面名称`/`题目名称` 或类型错误 | 503 `lark_publisher_configuration_error` | 同上；不创建无标题行 | 修复 Base schema 后重试 |
| Skill 输入缺少题目或 Base 出现有答案无题目 | `invalid_payload` / `variant_answer_without_question` | 原题和 Base 现有变式 | 补齐题目或清理孤立答案后重新校验；有题无答案无需处理 |
| Skill 写回发现已有内容 | `generation_conflict` | 旧变式完整保留 | 教师确认是否覆盖整组 |
| Skill 写回/限流失败 | 安全 Lark 错误 + retryable | 原题、旧变式、勾选状态 | 修复后逐记录重试 |
| 独立变式记录缺少唯一来源、题干或稳定键 | `variant_invalid` | 原题与既有变式不变 | 补齐输入后重新校验；不创建半成品行 |
| 含图变式缺少题图或上传回读失败 | `diagram_incomplete` | 原题、既有变式和本地 HTML/PNG | 修复题图后重试该次写入；未完成前不得声称成功 |
| 覆盖整组时已有题图附件 | `diagram_replace_requires_cleanup` | 旧题图和旧变式不变 | 教师先在 Base 确认并清理旧附件 |
| 再练事件文件损坏 | `event_store_invalid` | Base 与原始错例不变 | 备份/修复本地 JSONL 后重试 |
| 读取不存在 ID | 404 `problem_not_found` | 无变化 | 检查链接/ID |

## 13. 隐私流向

- 浏览器 → 本地 FastAPI：完整上传图片、bbox、修订文本。
- FastAPI → 托管 PaddleOCR-VL（当前真实默认）：只发送教师所选题目裁图到官方 Job API，Token 只来自环境变量；Provider raw 与人工修订分层保存。本地 PaddleOCR Adapter 仍可作为隔离配置，但不是当前默认。
- FastAPI → Yescan（仅 chat/兼容检测入口）：按教师已授权范围发送整页图片；完整返回写入私有 evidence storage，API/日志不返回 Base64 或完整识别文本。
- FastAPI → Lark Base（仅教师显式发布）：发送来源整页、题目裁图、教师修订文本及最小发布元数据；不发送 OCR raw response、API Key、完整本地修订历史或本机绝对路径。
- Codex/Hermes → MinerU/PDF/doc（仅 PDF/Word 路径）：告知教师后发送或渲染材料，保留逐页视觉；结构化文本只辅助识别，不能替代原页。
- Codex/Hermes Skill ↔ Lark Base（明确发布/选题/写回）：先把教师确认修订的原题发布为目录记录；教师确认后可按共同错误建立 `错题记录` 并在 `对应学生` 多选中保存姓名/代号；以后只读取教师选中的原题、错误组和必要图片上下文，写入编号变式题、可选答案解析、同编号题图及当前再练摘要。不遍历整库，不把学生名单发给 OCR Provider，也不内置模型或飞书密钥。
- 日志：只含 ID、状态、长度、耗时和安全错误码。
- MinerU 在当前仅承担 Agent 层 PDF/Word 结构辅助；若未来让 MinerU/Doc2X 成为 FastAPI 正式 OCR Provider，仍需独立任务记录运行、原始响应和教师选择规则。
