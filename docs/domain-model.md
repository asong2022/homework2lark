# Phase 1 领域模型

## 1. 建模原则

1. 经过教师审核的数学题目是最小可复用教学资产。
2. OCR 是不可覆盖的机器证据，不是题目真值。
3. 原始、机器派生、人工修订三层分离。
4. `ReviewedProblem` 表示题目资产与审核门槛；Base `MistakeGroupRecord` 汇总同题同类错误学生，未来原子级 `MistakeOccurrence` 表示单个学生的一次错误事实，三者禁止混为一体。
5. 图像、图形、表格和批改痕迹通过 SourceAsset + ProblemRegion + crop 保留，不能只保存文本。

## 2. 当前实体

### 2.1 SourceAsset

教师上传的不可变原始材料。

| 字段 | 类型/约束 | 职责 |
|---|---|---|
| `id` | `asset_` UUID，PK | 公共标识 |
| `file_name` | 非空字符串 | 原始显示名，不作为路径 |
| `media_type` | 当前 `image/jpeg`/`image/png` | 为未来 PDF 扩展保留类型能力 |
| `storage_key` | 唯一、不透明 | StorageAdapter 内的原图位置 |
| `file_hash` | SHA-256，索引 | 重复文件判断 |
| `width`/`height` | 正整数 | 应用 EXIF orientation 后的显示像素尺寸 |
| `file_size` | 正整数 | 字节数 |
| `created_at` | UTC | 创建时间 |

约束：原图 storage key 不被裁图或 OCR 写入覆盖；数据库不保存绝对路径或二进制。读取/裁图时在内存中应用 EXIF orientation，绝不重写原始文件。

### 2.2 RegionDetectionRun 与 RegionCandidate

一次自动框题产生一个不可覆盖的 `RegionDetectionRun`，其下每个 `RegionCandidate` 是 Provider 返回的一条题目级建议。Yescan 中它与一个 group-level `StructureInfo` 一一对应；题内文字、公式、图形、表格或示意图 `Detail` 不会再拆成候选。Provider 仍可能误合并或误切，因此候选不具备审核状态，也不是可复用题目资产。

完整 Provider 响应保存在私有 evidence storage；数据库保存运行状态、Provider/模型、耗时、警告和候选像素 bbox。重新检测创建新 run，不覆盖旧候选。

### 2.3 ProblemRegionCandidateSource

有序关联一个教师确认的 `ProblemRegion` 与一个或多个 `RegionCandidate`。若 Provider 把一道含文字与图片的题误切为两个题目框，教师显式合并后，关联表保留两个候选 ID，但只生成一个题目区域、裁图和 problem ID。每个候选最多归入一个已保存逻辑题目。

### 2.4 ProblemRegion

教师在一个 SourceAsset 中确认的题目区域。

| 字段 | 类型/约束 | 职责 |
|---|---|---|
| `id` | `region_` UUID，PK | 区域标识 |
| `source_asset_id` | FK | 绑定唯一来源 |
| `page_number` | 当前固定 1 | 为未来 PDF 页保留 |
| `x/y` | 大于等于 0 的整数 | 原图上的左上角像素坐标 |
| `width/height` | 正整数 | 区域像素尺寸 |
| `coordinate_system` | `pixel_top_left` | 明确原点和单位 |
| `cropped_asset_key` | 唯一 | PNG 裁图位置 |
| `selection_source` | `manual/detected` | 教师最终区域来源 |
| `detection_candidate_id` | 可空 FK | 首个候选兼容字段；完整来源以关联表为准 |
| `created_at` | UTC | 创建时间 |

请求中的 normalized bbox 不是持久化真值；后端以 SourceAsset 尺寸转换并验证。

### 2.5 OCRRun

一次机器识别尝试。运行先以 `running` 创建，随后完成为 `succeeded` 或 `failed`。

| 字段 | 类型/约束 | 职责 |
|---|---|---|
| `id` | `ocr_` UUID，PK | 运行标识 |
| `problem_region_id` | FK，索引 | 被识别区域 |
| `provider` | 非空 | 统一 Provider 名称 |
| `provider_model`/`provider_version` | 可空 | 模型与适配器/运行版本 |
| `raw_response` | JSON，可空 | JSON-safe 原始结果/安全失败元数据 |
| `extracted_text` | 文本，可空 | 适配后的标准文本 |
| `confidence` | 0..1，可空 | 聚合置信度 |
| `status` | `running/succeeded/failed` | 运行状态 |
| `error_code` | 可空 | 安全、稳定的 Provider 错误分类 |
| `started_at`/`finished_at` | UTC | 运行时间 |
| `processing_time_ms` | 非负，可空 | Provider 耗时 |

约束：重试创建新行；完成后不修改为另一份结果。业务层不解析 Vendor 专有字段。

### 2.6 ProblemRevision

教师基于某次成功 OCRRun 保存的一次人工修订。

| 字段 | 类型/约束 | 职责 |
|---|---|---|
| `id` | `revision_` UUID，PK | 修订标识 |
| `problem_region_id` | FK | 所属区域 |
| `based_on_ocr_run_id` | FK | 机器证据基线 |
| `revision_number` | 每区域从 1 递增 | 人工版本序号 |
| `corrected_text` | 非空文本 | 教师确认前的修订内容 |
| `correction_note` | 可空 | 修订说明 |
| `created_at` | UTC | 创建时间 |

唯一约束：`(problem_region_id, revision_number)`。每次保存新版本，不更新旧行。

### 2.7 ReviewedProblem

题目资产聚合入口。名称表示它具备审核生命周期，不表示当前一定已经 reviewed。

| 字段 | 类型/约束 | 职责 |
|---|---|---|
| `id` | `problem_` UUID，PK | 对外 `problemId` |
| `problem_region_id` | FK，唯一 | 一区域对应一个当前题目资产 |
| `current_revision_id` | FK，可空 | 最近保存或审核时明确选中的人工版本 |
| `review_status` | 枚举 | 当前审核状态 |
| `reviewed_at` | UTC，可空 | 最近确认审核时间 |
| `created_at`/`updated_at` | UTC | 生命周期时间 |

领域规则：`future_reuse_eligible = review_status == reviewed AND current_revision_id 有效`。该值计算输出，不单独持久化，避免漂移。

### 2.8 ReviewStatusEvent

记录审核状态变化，满足“状态变化可追踪”。

| 字段 | 类型/约束 | 职责 |
|---|---|---|
| `id` | `review_event_` UUID，PK | 事件标识 |
| `reviewed_problem_id` | FK | 所属问题 |
| `from_status` | 可空 | 初始创建时为空 |
| `to_status` | 枚举 | 新状态 |
| `reason` | 稳定代码 | `region_created`、`ocr_text_ready`、`ocr_empty`、`revision_saved`、`teacher_reviewed` |
| `ocr_run_id` | FK，可空 | 引起变化的 OCR 版本 |
| `revision_id` | FK，可空 | 引起变化/被审核的人工版本 |
| `created_at` | UTC | 发生时间 |

## 3. 实体关系

```text
SourceAsset 1 ── N RegionDetectionRun
RegionDetectionRun 1 ── N RegionCandidate
SourceAsset 1 ── N ProblemRegion
ProblemRegion 1 ── N ProblemRegionCandidateSource N ── 1 RegionCandidate
ProblemRegion 1 ── N OCRRun
ProblemRegion 1 ── N ProblemRevision
OCRRun 1 ── N ProblemRevision
ProblemRegion 1 ── 1 ReviewedProblem
ProblemRevision 0..1 ← current ── ReviewedProblem
ReviewedProblem 1 ── N ReviewStatusEvent

Future only:
ReviewedProblem 1 ── N MistakeOccurrence

Current Base projection only:
ReviewedProblem 1 ── N MistakeGroupRecord ── N student labels
```

## 4. 生命周期

### 4.1 来源与区域

`SourceAsset` 创建成功后长期不可变。创建区域时生成 crop；若 crop 或数据库创建失败，只补偿本次新 crop，不删除 source。

### 4.2 OCR

```text
running → succeeded (text or empty)
        → failed
```

失败不删除区域。再次识别从新的 `running` OCRRun 开始。

### 4.3 审核状态机

```text
draft
  ├─ OCR 非空成功 ───────────→ needs_review
  └─ OCR 空文本成功 ─────────→ ocr_completed

ocr_completed ─ 保存人工修订 → needs_review（并设为 current revision）
needs_review  ─ 保存新修订 ──→ needs_review（切换 current revision）
needs_review  ─ 教师确认 ────→ reviewed
reviewed      ─ 单独重试 OCR ─→ reviewed
reviewed      ─ 保存新修订 ──→ needs_review（清空 reviewed_at）
```

OCR 失败不改变当前 review status。重新修订已审核题会撤回复用资格，要求重新审核。

## 5. 当前与未来实体

当前本地 API 实现上述题目实体与关联关系。Base 额外实现轻量 `MistakeGroupRecord` 投影：一行按题目、日期和共同错误表现汇总多名学生标签，不在 SQLite 中新增学生实体。

未来可挂接但不实现：

- `MistakeOccurrence`：学生/班级在某时某来源下的一次错误事实。
- `PracticeTask`、`PracticeAttempt`、`MasteryState`：再练与掌握。
- `ProblemTagging`：年级、教材、单元、知识点、核心素养、认知层级、情境、表征、难度。
- `MistakeDiagnosis`：错误类型、原因、证据与教师诊断。
- `ProblemVariant`：原题与巩固/变式/拓展/提升题的有向关系。
- `ImageGenerationProvider`/`DiagramProvider`：未来含图题的图形生成/编辑端口概念，不在 Phase 1 编码。

当前 Base 中 `错题记录` 是 `MistakeGroupRecord`：同一道题、同一次作业、同一种错误表现的一组学生，是对多个概念性错误事件的教师友好聚合。题目行的 `典型错例` 与 `错误表现` 只是这些分组的只读 lookup，`错误原因` 是带人数的汇总投影，都不是新的领域实体。只有需要原子级逐学生历史、身份合并或正式统计时，才实现本地 `MistakeOccurrence`。

## 6. 禁止混淆的概念

- SourceAsset ≠ ProblemRegion：一个来源可含多题，区域必须能回到来源定位。
- RegionCandidate ≠ ProblemRegion：候选是 Provider 题目建议；Provider 误切时一道题可以引用多个候选，但仍只有一个教师确认的逻辑题目。
- OCRRun ≠ ProblemRevision：机器输出不可被人工文字覆盖。
- ProblemRevision ≠ ReviewedProblem：修订存在不等于审核完成。
- ReviewedProblem ≠ MistakeOccurrence：题目资产不是某个学生的一次错误。
- 题目学情 lookup ≠ MistakeOccurrence：聚合视图不能承担逐人、逐次作答历史。
- MistakeGroupRecord ≠ MistakeOccurrence：Base 分组行可包含多名同类错误学生，不是一个学生一行的原子事实。
- `reviewed` ≠ OCR 成功：人工质量门槛不可由 Provider 绕过。
- 规范化记录 ≠ 新数据库实体：它是聚合读取契约，不重复存储所有字段。
