# Phase 1 API Contract

## 1. 约定

- Base URL：`/api/v1`。
- JSON 字段：camelCase；数据库列不对外暴露。
- 时间：UTC ISO 8601。
- ID：带领域前缀的字符串。
- 二进制：原图/裁图使用独立内容端点，不在 JSON 中返回 base64/绝对路径。
- 契约权威：FastAPI 生成的 OpenAPI；提交 `packages/contracts/openapi.json` 并生成 Web TypeScript 类型。

## 2. 错误响应

```json
{
  "error": {
    "code": "invalid_region",
    "message": "框选区域超出原图范围，请重新框选。",
    "details": {},
    "requestId": "req_...",
    "retryable": false
  }
}
```

进入 FastAPI 路由、校验和应用异常链的非 2xx 响应都使用该 envelope。Provider/数据库/文件系统原始异常不得直出。被 CORS middleware 在路由前拒绝的预检仍由 Starlette 返回安全的 plain-text 400；外层请求中间件继续添加 `X-Request-ID`，浏览器端把它视为网络/CORS 错误。
框架级 malformed multipart 返回 400 `bad_request`；不存在路由和不支持的方法也分别使用 404 `route_not_found`、405 `method_not_allowed` 的同一 envelope。

## 3. 端点

### `POST /assets`

`multipart/form-data`，字段 `file`。接受 JPG/JPEG/PNG，默认最大 15 MiB。

- `201`: `SourceAssetResponse`，含 `assetId`, metadata, `contentUrl`, `duplicateOfAssetId|null`。
- `400`: malformed multipart 的 `bad_request`。
- `413`: `asset_too_large`。
- `415`: `unsupported_image`。
- `422`: `invalid_image`。

Hash 只用于提示重复，不自动合并/替换 SourceAsset。

### `GET /assets/{assetId}`

- `200`: SourceAsset metadata（不含 bytes）。
- `404`: `asset_not_found`。

### `GET /assets/{assetId}/content`

- `200`: 原始图片 bytes，正确 Content-Type、ETag/hash 和 `X-Content-Type-Options: nosniff`。
- 浏览器与后端都按 EXIF orientation 解释显示方向；原始 bytes 不变。

### `GET /assets/{assetId}/problems`

- `200`: `{ assetId, count, items }`，其中每项都是完整 `NormalizedProblemResponse`。
- 按题框上、左坐标稳定排序；响应使用 `Cache-Control: no-store`。
- 已存在但未框题的来源页返回空集合；不存在的 asset 返回 404 `asset_not_found`。
- Web 用该接口恢复同一原图上的已保存题框，不把 OCR/修订文本写入 URL 或本地存储。

### `POST /assets/{assetId}/regions`

请求：

```json
{
  "coordinateSystem": "normalized_top_left",
  "bbox": { "x": 0.05, "y": 0.13, "width": 0.72, "height": 0.21 }
}
```

- `201`: `RegionCreateResponse`，含 `regionId`, `problemId`, canonical pixel bbox, `cropContentUrl`。
- `422`: 非有限、越界、零面积或转换后过小的 `invalid_region`。
- `404`: asset 不存在。

### `GET /regions/{regionId}/crop`

- `200`: 服务端生成的 PNG crop。
- `404`: `region_not_found` 或 `crop_not_found`。

### `POST /regions/{regionId}/ocr-runs`

请求可省略 body；语言/允许的非敏感选项由服务端配置。

- `201`: 完成的 `OCRRunResponse`，包括 raw response、标准 text、blocks、warnings、timing。空文本也是 201 + `ocr_empty_text` warning。
- `502`: `ocr_invalid_response`。
- `503`: `ocr_provider_unavailable`/`ocr_provider_configuration_error`。
- `504`: `ocr_timeout`。
- 每次请求创建新 run；失败 run 也持久化，原图/区域/crop 保留。

### `POST /regions/{regionId}/revisions`

```json
{
  "basedOnOcrRunId": "ocr_...",
  "correctedText": "教师修订后的完整题目",
  "correctionNote": "可选说明"
}
```

- `201`: 新 `ProblemRevisionResponse`，含递增 revision number。
- `422`: 空文字或 OCR run 无效/不属于 region。
- 新 revision 立即成为 `ProblemAsset.currentRevisionId`；不再需要第二次审核调用。

### `GET /problems/{problemId}`

- `200`: `NormalizedProblemRecord`。
- `404`: `problem_not_found`。
- 响应使用 `Cache-Control: no-store`，避免保存修订后仍显示旧版本。

### `POST /problems/{problemId}/publications/lark`

- `201`: 当前 `ProblemPublicationResponse`。
- `409`: 没有非空当前修订，或来源、裁图、OCR 依据不完整时返回 `problem_not_publishable`。
- `502/503`: 飞书返回异常、登录/Schema 配置错误或暂时不可用；本地证据和当前修订保持不变。
- 重试复用同一 `problemId` 的本地发布状态和远端隐藏稳定键，不重复创建题目。

### `GET /health`

- `200`: API/数据库基本状态与当前 Provider 名称；不触发重型模型推理、不暴露配置/路径/密钥。

## 4. 请求一致性与重试

- 上传/创建 region 不做透明重试，避免重复资产；UI 只在明确失败时由教师再次操作。
- OCR retry 是新 POST/new run，天然保留历史。
- revision save 是新版本；前端 pending 时禁止双击。Phase 1 单教师下不增加复杂幂等键。
- publication 总是读取服务端当前修订，不接受客户端伪造 revision ID 或修订内容。

## 5. OpenAPI 同步

后端脚本从 `app.openapi()` 导出 `packages/contracts/openapi.json`；Web 使用 `openapi-typescript` 生成唯一的 `generated-api.ts`。后端测试检查提交的 OpenAPI 快照，schema 变化必须在同一任务更新生成类型和前端用法。
