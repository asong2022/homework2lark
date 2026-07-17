# 规范化题目记录

`GET /api/v1/problems/{problemId}` 返回一条可追溯的题目资产记录。它把来源、裁图、OCR、教师修订和飞书发布结果组合为一个读取模型，但不复制或覆盖任何上游证据。

## 顶层字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `problemId` | string | `ProblemAsset.id`，稳定公开 ID |
| `source` | object | 原始页面及内容地址 |
| `region` | object | 题目区域、裁图地址及框选来源 |
| `ocr` | object/null | 当前人工修订所依据的 OCR；尚无修订时为最近一次成功 OCR |
| `latestOcrRun` | object/null | 最近一次 OCR 尝试，可能失败 |
| `humanRevision` | object/null | 当前教师确认修订 |
| `lineage` | object | 当前来源、区域、OCR 和修订 ID |
| `history` | object | 全部 OCR 尝试与人工修订，按时间/版本升序 |
| `publication` | object/null | 当前飞书发布状态 |
| `createdAt` / `updatedAt` | ISO UTC string | 题目资产创建时间和当前修订指针更新时间 |

记录不包含 `status`、`review`、`reviewedAt`、`statusHistory` 或 `futureReuseEligible`。产品不维护第二套“待审核/已审核”状态机。

## 当前版本规则

1. 每次 OCR 都新增 `OCRRun`，失败与重试不会覆盖旧运行。
2. 每次保存教师修订都新增 `ProblemRevision`，版本号在同一区域内递增。
3. 新修订保存成功后立即成为 `ProblemAsset.current_revision_id`。
4. `ocr` 跟随当前修订的 `basedOnOcrRunId`，所以后续失败 OCR 不会改变当前题目依据。
5. 没有非空当前修订时禁止发布；存在当前修订且来源、裁图、OCR 依据完整时可以发布。

## 精简示例

```json
{
  "problemId": "problem_example",
  "source": {
    "assetId": "asset_example",
    "fileName": "worksheet.png",
    "mediaType": "image/png",
    "fileHash": "sha256-value",
    "width": 1200,
    "height": 1600,
    "fileSize": 2048,
    "contentUrl": "/api/v1/assets/asset_example/content",
    "duplicateOfAssetId": null,
    "createdAt": "2026-07-17T08:00:00Z"
  },
  "region": {
    "regionId": "region_example",
    "pageNumber": 1,
    "coordinateSystem": "pixel_top_left",
    "bbox": {"x": 100, "y": 200, "width": 800, "height": 400},
    "cropContentUrl": "/api/v1/regions/region_example/crop",
    "selectionSource": "manual",
    "detectionCandidateId": null,
    "detectionCandidateIds": [],
    "createdAt": "2026-07-17T08:01:00Z"
  },
  "ocr": {
    "runId": "ocr_example",
    "provider": "paddleocr_vl_api",
    "model": "PaddleOCR-VL-1.6",
    "text": "机器识别的题干",
    "status": "succeeded",
    "errorCode": null,
    "blocks": [],
    "rawResponse": {},
    "warnings": [],
    "startedAt": "2026-07-17T08:02:00Z",
    "finishedAt": "2026-07-17T08:02:03Z",
    "processingTimeMs": 3000
  },
  "latestOcrRun": {"runId": "ocr_example", "status": "succeeded"},
  "humanRevision": {
    "revisionId": "revision_example",
    "basedOnOcrRunId": "ocr_example",
    "revisionNumber": 1,
    "correctedText": "教师确认后的完整题目",
    "correctionNote": "修正 OCR",
    "createdAt": "2026-07-17T08:03:00Z"
  },
  "lineage": {
    "sourceAssetId": "asset_example",
    "problemRegionId": "region_example",
    "detectionCandidateId": null,
    "detectionCandidateIds": [],
    "ocrRunId": "ocr_example",
    "revisionId": "revision_example"
  },
  "history": {
    "ocrRuns": [],
    "revisions": []
  },
  "publication": null,
  "createdAt": "2026-07-17T08:01:00Z",
  "updatedAt": "2026-07-17T08:03:00Z"
}
```

完整字段、必填性和枚举以 `packages/contracts/openapi.json` 为准。示例为阅读方便省略了部分可空 OCR 字段，不能替代运行时契约。

## 后续复用

飞书 Base 中的 `本地修订版本` 与隐藏 `系统题目ID` 用于幂等同步。是否进入变式、练习或反馈流程，由实际内容完整性、有效来源关系和 `需人工处理` 例外标记决定，不再依赖审核时间或审核状态。
