# Normalized Problem Record Spec

## 1. 目的

`NormalizedProblemRecord` 是按 `problemId` 重建的一致读取视图，不是新的数据库表。它把来源、区域、OCR、人工版本、审核、发布状态和 lineage 组织为前端可稳定消费的 camelCase JSON，同时保留历史数组用于追溯。

FastAPI OpenAPI 是契约权威；`packages/contracts/openapi.json` 与生成的 TypeScript 类型必须与它一致。

## 2. 顶层结构

| 字段 | 类型 | 来源/规则 |
|---|---|---|
| `problemId` | string | ReviewedProblem.id |
| `status` | ReviewStatus | ReviewedProblem.review_status |
| `futureReuseEligible` | boolean | 后端领域规则计算，不接受客户端输入 |
| `source` | SourceRecord | SourceAsset |
| `region` | RegionRecord | ProblemRegion |
| `ocr` | OCRRecord/null | 当前人工修订的 based-on run；无修订时优先取最新成功 run，无成功 run 才取最新尝试 |
| `latestOcrRun` | OCRRecord/null | 该区域时间上最新的一次尝试，可能失败；用于展示恢复状态，与 `ocr` 的教师基线语义分离 |
| `humanRevision` | RevisionRecord/null | ReviewedProblem.current_revision_id |
| `review` | ReviewRecord | 当前状态和历史 |
| `lineage` | LineageRecord | 当前选中版本的显式 ID 链 |
| `history` | HistoryRecord | 全部 OCR runs 与 revisions（按创建顺序） |
| `publication` | PublicationRecord/null | 当前飞书发布状态；从未发布时为 null |
| `createdAt`/`updatedAt` | ISO UTC string | ReviewedProblem |

## 3. 字段定义

### SourceRecord

- `assetId`, `fileName`, `mediaType`, `storageKey`, `fileHash`, `width`, `height`, `fileSize`, `createdAt`。
- `contentUrl` 是浏览器可用的受控 API 相对 URL；前端不得从 storage key 拼接路径。
- `width/height` 是 EXIF orientation 后的显示尺寸；原始字节未改写。

### RegionRecord

- `regionId`, `pageNumber`, `coordinateSystem`, `bbox`, `croppedAssetKey`, `cropContentUrl`, `createdAt`。
- `selectionSource` 为 `manual` 或 `detected`；`detectionCandidateId` 保留首个候选兼容值，`detectionCandidateIds` 保存构成这道逻辑题的全部 Provider 题目框 ID。
- Provider 把一道题误切成多个框并由教师合并后，仍只有一个 RegionRecord、一个 bbox 和一个裁图；来源框不会被序列化成多道题。
- `bbox` 的 x/y 可为 0，width/height 必须大于 0；单位为原图显示像素。

### OCRRecord

- `runId`, `provider`, `model`, `providerVersion`, `text`, `confidence`, `status`, `errorCode`, `blocks`, `rawResponse`, `warnings`, `startedAt`, `finishedAt`, `processingTimeMs`。
- 失败 run 的 text 可为空且 rawResponse 只含安全失败元数据；Vendor 异常文本不外泄。

### RevisionRecord

- `revisionId`, `basedOnOcrRunId`, `revisionNumber`, `correctedText`, `correctionNote`, `createdAt`。
- 新修订保存后立即成为 current revision，但状态为 `needs_review`，直至再次审核。

### ReviewRecord

- `status`, `reviewedAt`, `statusHistory`。
- status history 事件含 `eventId`, `fromStatus`, `toStatus`, `reason`, `ocrRunId`, `revisionId`, `createdAt`。

### LineageRecord

- `sourceAssetId`, `problemRegionId`, `detectionCandidateId`, `detectionCandidateIds`, `ocrRunId`, `revisionId`。
- 没有 OCR/修订时相应值为 `null`，不可填虚构 ID。
- 手动框题的候选字段分别为 `null` 和空数组；自动/组合题的首个兼容 ID 必须等于数组第一项。

### HistoryRecord

- `ocrRuns`: 同一 region 的全部运行，含失败尝试。
- `revisions`: 同一 region 的全部人工版本。
- 当前项仍在对应数组中，通过顶层 `ocr`/`humanRevision` 和 lineage 指明。

### PublicationRecord

- `publicationId`, `publisher`, `status`, `publishedRevisionId`, `baseName`。
- `pagesTableId`, `questionsTableId`, `pageRecordId`, `questionRecordId` 在 pending/failed 时可为空，succeeded 时必须完整。
- `errorCode` 只保存安全分类；`retryable` 由后端分类派生。
- `startedAt`, `finishedAt`, `updatedAt` 为 UTC。
- 该对象是当前同步工作流状态，不替代 append-only OCR/Revision/Review history。

## 4. 示例 JSON

```json
{
  "problemId": "problem_018f2a90-5a8b-7d2e-a5dd-7d9b3aa03160",
  "status": "reviewed",
  "futureReuseEligible": true,
  "source": {
    "assetId": "asset_018f2a8d-5b2e-7d24-9830-7338bfb02f51",
    "fileName": "worksheet-01.jpg",
    "mediaType": "image/jpeg",
    "storageKey": "sources/2026/07/asset_018f2a8d.jpg",
    "fileHash": "b8f7...sha256",
    "width": 2480,
    "height": 3508,
    "fileSize": 1824032,
    "contentUrl": "/api/v1/assets/asset_018f2a8d-5b2e-7d24-9830-7338bfb02f51/content",
    "createdAt": "2026-07-12T08:00:00Z"
  },
  "region": {
    "regionId": "region_018f2a8e-8ccb-7bc9-843d-ecba4203c89e",
    "pageNumber": 1,
    "coordinateSystem": "pixel_top_left",
    "bbox": { "x": 120, "y": 460, "width": 1800, "height": 720 },
    "croppedAssetKey": "crops/asset_018f2a8d/region_018f2a8e.png",
    "cropContentUrl": "/api/v1/regions/region_018f2a8e-8ccb-7bc9-843d-ecba4203c89e/crop",
    "selectionSource": "detected",
    "detectionCandidateId": "candidate_text_01",
    "detectionCandidateIds": ["candidate_text_01", "candidate_diagram_01"],
    "createdAt": "2026-07-12T08:01:00Z"
  },
  "ocr": {
    "runId": "ocr_018f2a8f-7335-7aa4-8c64-f27131074446",
    "provider": "fake",
    "model": "deterministic-v1",
    "providerVersion": "1.0",
    "text": "小明有24本书，平均放在6层书架上，每层放几本？",
    "confidence": 0.99,
    "status": "succeeded",
    "errorCode": null,
    "blocks": [
      {
        "type": "text",
        "text": "小明有24本书，平均放在6层书架上，每层放几本？",
        "bbox": { "x": 12, "y": 18, "width": 620, "height": 54 },
        "confidence": 0.99,
        "readingOrder": 0,
        "metadata": {}
      }
    ],
    "rawResponse": { "engine": "fake", "lines": 1 },
    "warnings": [],
    "startedAt": "2026-07-12T08:01:02Z",
    "finishedAt": "2026-07-12T08:01:02Z",
    "processingTimeMs": 5
  },
  "latestOcrRun": {
    "runId": "ocr_018f2a8f-7335-7aa4-8c64-f27131074446",
    "provider": "fake",
    "model": "deterministic-v1",
    "providerVersion": "1.0",
    "text": "小明有24本书，平均放在6层书架上，每层放几本？",
    "confidence": 0.99,
    "status": "succeeded",
    "errorCode": null,
    "blocks": [],
    "rawResponse": { "engine": "fake", "lines": 1 },
    "warnings": [],
    "startedAt": "2026-07-12T08:01:02Z",
    "finishedAt": "2026-07-12T08:01:02Z",
    "processingTimeMs": 5
  },
  "humanRevision": {
    "revisionId": "revision_018f2a90-0b4a-7597-af9d-f6d8364e63f5",
    "basedOnOcrRunId": "ocr_018f2a8f-7335-7aa4-8c64-f27131074446",
    "revisionNumber": 1,
    "correctedText": "小明有24本书，平均放在6层书架上，每层放几本？",
    "correctionNote": "核对标点",
    "createdAt": "2026-07-12T08:02:00Z"
  },
  "review": {
    "status": "reviewed",
    "reviewedAt": "2026-07-12T08:03:00Z",
    "statusHistory": [
      {
        "eventId": "review_event_018f2a8e",
        "fromStatus": null,
        "toStatus": "draft",
        "reason": "region_created",
        "ocrRunId": null,
        "revisionId": null,
        "createdAt": "2026-07-12T08:01:00Z"
      },
      {
        "eventId": "review_event_018f2a8f",
        "fromStatus": "draft",
        "toStatus": "needs_review",
        "reason": "ocr_text_ready",
        "ocrRunId": "ocr_018f2a8f-7335-7aa4-8c64-f27131074446",
        "revisionId": null,
        "createdAt": "2026-07-12T08:01:02Z"
      },
      {
        "eventId": "review_event_018f2a91",
        "fromStatus": "needs_review",
        "toStatus": "reviewed",
        "reason": "teacher_reviewed",
        "ocrRunId": null,
        "revisionId": "revision_018f2a90-0b4a-7597-af9d-f6d8364e63f5",
        "createdAt": "2026-07-12T08:03:00Z"
      }
    ]
  },
  "lineage": {
    "sourceAssetId": "asset_018f2a8d-5b2e-7d24-9830-7338bfb02f51",
    "problemRegionId": "region_018f2a8e-8ccb-7bc9-843d-ecba4203c89e",
    "detectionCandidateId": "candidate_text_01",
    "detectionCandidateIds": ["candidate_text_01", "candidate_diagram_01"],
    "ocrRunId": "ocr_018f2a8f-7335-7aa4-8c64-f27131074446",
    "revisionId": "revision_018f2a90-0b4a-7597-af9d-f6d8364e63f5"
  },
  "history": {
    "ocrRuns": [
      {
        "runId": "ocr_018f2a8f-7335-7aa4-8c64-f27131074446",
        "provider": "fake",
        "model": "deterministic-v1",
        "providerVersion": "1.0",
        "text": "小明有24本书，平均放在6层书架上，每层放几本？",
        "confidence": 0.99,
        "status": "succeeded",
        "errorCode": null,
        "blocks": [],
        "rawResponse": { "engine": "fake", "lines": 1 },
        "warnings": [],
        "startedAt": "2026-07-12T08:01:02Z",
        "finishedAt": "2026-07-12T08:01:02Z",
        "processingTimeMs": 5
      }
    ],
    "revisions": [
      {
        "revisionId": "revision_018f2a90-0b4a-7597-af9d-f6d8364e63f5",
        "basedOnOcrRunId": "ocr_018f2a8f-7335-7aa4-8c64-f27131074446",
        "revisionNumber": 1,
        "correctedText": "小明有24本书，平均放在6层书架上，每层放几本？",
        "correctionNote": "核对标点",
        "createdAt": "2026-07-12T08:02:00Z"
      }
    ]
  },
  "publication": {
    "publicationId": "publication_018f2a91-f247-70bd-9bd7-dc48e09ed425",
    "publisher": "lark_cli",
    "status": "succeeded",
    "publishedRevisionId": "revision_018f2a90-0b4a-7597-af9d-f6d8364e63f5",
    "baseName": "小学数学错题学习库",
    "pagesTableId": "tbl_pages",
    "questionsTableId": "tbl_questions",
    "pageRecordId": "rec_page",
    "questionRecordId": "rec_question",
    "errorCode": null,
    "retryable": false,
    "startedAt": "2026-07-12T08:04:00Z",
    "finishedAt": "2026-07-12T08:04:03Z",
    "updatedAt": "2026-07-12T08:04:03Z"
  },
  "createdAt": "2026-07-12T08:01:00Z",
  "updatedAt": "2026-07-12T08:03:00Z"
}
```

## 5. 版本选择规则

1. 保存修订：新 revision 成为 current，状态转/保持 `needs_review`。
2. 审核：显式 revision 成为 current，状态变为 `reviewed`。
3. 单独 OCR 重试：追加 history；若当前 revision 存在，顶层 `ocr` 仍指向其 based-on run，不擅自替换教师基线。
4. 无 revision：顶层 `ocr` 优先指向最新成功 run；如果从未成功，才指向最新失败/空尝试。`latestOcrRun` 始终指向时间上最新尝试，lineage revision 为 null。
5. 新修订基于最新或明确选择的成功 run；不得引用其他 region 的 run。

## 6. 后续挂接点

未来 `MistakeOccurrence.problem_id`、`PracticeTask.source_problem_id`、`ProblemVariant.source_problem_id`、`MasteryState` 的关系从 `ReviewedProblem.id` 出发。所有正式使用入口必须先检查 `futureReuseEligible`；未审核题不得进入生成、专题或学生任务候选池。
