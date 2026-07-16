# OCR Provider 抽象

## 1. 目标与边界

统一 Provider 层只负责“把一道题的裁图识别为可持久化的标准结果”。它不决定题目是否正确、不修改人工版本、不选择多个 Provider，也不自动重试、降级或投票。

业务层依赖 `OCRProvider`，不依赖 PaddleOCR/MinerU/Quark Yescan/Doc2X 的返回结构、认证方式或 SDK 类型。

## 2. Python 协议

```python
from dataclasses import dataclass, field
from typing import Protocol

class OCRProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model_name(self) -> str | None: ...

    def recognize(self, input: OCRInput) -> OCRResult: ...

    def health_check(self) -> ProviderHealth: ...
```

协议刻意保持同步，以继续复用现有 Application Service 的追加运行、超时和失败持久化语义。本地 PaddleOCR 直接执行同步推理；官方托管 PaddleOCR-VL Adapter 在同一次 `recognize` 内部提交 Job、轮询并下载 JSONL。Application Service 在独立 daemon worker 中调用并用 `OCR_TIMEOUT_SECONDS` 等待结果；Adapter 自身的轮询截止时间略短于业务截止时间。`health_check` 只检查配置，不发网络请求，也不参与自动路由。

## 3. 输入协议

```python
@dataclass(frozen=True, slots=True)
class OCRInput:
    source_asset_id: str
    problem_region_id: str
    image_bytes: bytes
    media_type: str = "image/png"
    language: str = "ch"
    options: dict[str, JsonValue] = field(default_factory=dict)
```

规则：

- 输入是已经由服务端裁切的题目图片，不传完整作业页给 Provider。
- `image_bytes` 不进入日志或数据库；数据库保存 crop storage key。
- `options` 只能来自服务端允许列表，不能让客户端传任意 Provider 参数或密钥。
- source/region ID 用于追踪和日志，不作为 Provider 文件路径。

## 4. 输出协议

```python
@dataclass(frozen=True, slots=True)
class OCRResult:
    provider: str
    model: str | None
    provider_version: str | None
    text: str
    confidence: float | None
    blocks: list[OCRBlock]
    raw_response: JsonValue
    warnings: list[str]
    processing_time_ms: int

@dataclass(frozen=True, slots=True)
class OCRBlock:
    type: Literal["text", "formula", "table", "diagram", "unknown"]
    text: str
    bbox: BoundingBox | None
    confidence: float | None
    reading_order: int
    metadata: dict[str, JsonValue]
```

`BoundingBox` 使用裁图上的 `pixel_top_left` 坐标。Provider 不能表达的字段为 `null`，不能伪造置信度或 bbox。

## 5. 原始响应与标准化

- `raw_response` 完整保留每个 Provider SDK 结果的全部可序列化字段，包括 Paddle 结果中与 `res` 同级的 trace/诊断字段；Adapter 另取标准化视图，不能为了方便解析而丢弃外层字段。NumPy 数组/标量转换为 JSON primitive。
- 标准 `text` 按 `reading_order` 连接 block 文本；标准化只能做换行/空白等无语义整理，不更改数学内容。
- `confidence` 为 Provider 有意义时的聚合值；不可比的 Vendor 分数不做跨 Provider 统一排名。
- Provider 专有字段只放 `raw_response` 或 block `metadata`。
- `processing_time_ms` 覆盖 Adapter 收到输入后直至返回统一结果的总耗时，包括图像解码、模型惰性初始化、推理和标准化。
- 数据库存储 raw JSON；客户端详情可按需展示诊断 JSON，但默认界面只展示标准文本和 Provider 元数据。

## 6. PaddleOCRProvider

### 6.1 实现方式

- 使用 PaddleOCR 3.x 本地推理接口：`PaddleOCR(...).predict(image)`。
- 初始化关闭当前流程不需要的文档方向分类、去扭曲和文本行方向流水线，除非配置明确启用。
- 对每页/图结果读取 `rec_texts`、`rec_scores`、`rec_boxes` 或 `rec_polys`，转换为 `OCRBlock`。
- Adapter 动态导入 `paddleocr`/`paddle`，使 Fake 模式无需安装重型依赖。
- 模型实例在进程内惰性创建并复用；并发和进程模型在未来性能任务中再评估。

### 6.2 当前运行条件

- 项目 Python 固定 3.11；真实运行通过 `uv sync --extra paddleocr` 安装 PaddlePaddle 3.x 与 PaddleOCR 3.x。Fake 环境可以不安装该 extra。
- 首次真实运行需要下载检测/识别模型的网络和足够磁盘/内存；后续从用户 Paddle 模型缓存加载。
- Windows 下强制 `enable_mkldnn=False`，规避 Paddle 3.x oneDNN/PIR 属性转换崩溃；重新开启前必须增加 Windows 真实回归测试。
- PaddleOCR 3.7 的结果对象虽实现 Mapping，但可能包含不可 JSON 序列化的可视化 `Font` 对象；Adapter 必须优先调用结果的 `.json()`/`to_dict()` 再做通用 JSON-safe 转换。
- 本机已用 `image2.png` 第 8 题裁图完成真实 Paddle 推理，Provider/model/文本/置信度和 raw evidence 均保存。表格单元格会被标准文本顺序扁平化，因此仍以裁图加教师修订为可信内容。
- 若初始化失败，返回 `ocr_provider_configuration_error`；若推理运行失败，返回安全的 unavailable/timeout/invalid_response 分类。

### 6.3 隐私

本地 Adapter 不把题目图片上传到 PaddleOCR 托管 API。模型权重下载与图片传输是不同的数据流。

## 7. PaddleOCRVLAPIProvider

### 7.1 运行方式

- Provider 名称为 `paddleocr_vl_api`，模型为 `PaddleOCR-VL-1.6`；它是官方托管 API，不是本地 `PaddleOCR(...)` 模型名。
- `POST https://paddleocr.aistudio-app.com/api/v2/ocr/jobs` 以 multipart 发送题目裁图、model 和 `optionalPayload`，再携带 bearer Token 轮询 `pending/running/done/failed`。
- `done` 后只下载 Provider 给出的 HTTPS JSONL，下载时不转发 Authorization header；当前不下载 Markdown 图片或 `outputImages`。
- 按 JSONL 行序和 `layoutParsingResults` 顺序提取 `markdown.text`，保留公式、表格和图片 Markdown 引用；Provider 未给出 bbox/confidence 时使用 `null`，不伪造。
- `raw_response` 保存 submission、全部轮询 status 和解析后 JSONL；Token、Authorization header 和本地路径不进入 raw。

### 7.2 运行条件与隐私

- 只需 Python `requests`、出站 HTTPS 和有效 `PADDLEOCR_ACCESS_TOKEN`，不需要本地 PaddlePaddle、GPU 或 VLM 权重。
- Token 仅保存在 Git 忽略的 `.env`；Provider 对象 repr、异常、日志和前端都不得包含它。
- 启用时会把教师已确认的题目裁图发送给 PaddleOCR/AI Studio 官方云服务；不发 SourceAsset ID、本地 storage key、教师元数据或学生身份字段。
- 已使用用户授权的 `image2.png` 通过实际 API 纵向流程验证：Provider/model 正确，文本非空，raw 证据持久化，source/crop 仍可读。

## 8. FakeOCRProvider

- 默认返回固定、可辨识的中文小学数学题文本、blocks、raw response 和确定性置信度。
- 不访问网络或磁盘模型。
- 与真实 Provider 运行同一合约测试。
- 失败/超时 Fake 只通过测试依赖注入使用，生产 HTTP API 不接受“模拟失败”开关。
- 默认开发配置为 `OCR_PROVIDER=fake`，让教师可先验证整个资料闭环，再安装真实 OCR。

## 9. 错误模型

| Adapter 分类 | API code | HTTP | 是否可重试 |
|---|---|---:|---|
| 未安装/配置错误 | `ocr_provider_configuration_error` | 503 | 修复配置后 |
| 临时不可用 | `ocr_provider_unavailable` | 503 | 是 |
| 超时 | `ocr_timeout` | 504 | 是 |
| 返回格式错误 | `ocr_invalid_response` | 502 | 更换/修复 Provider 后 |
| 空文本 | 非异常；warning `ocr_empty_text` | 201 | 可选择重试或手工修订 |

异常发生时，应用先完成 OCRRun 为 `failed`，再返回错误；不得删除原图、区域或裁图。

## 10. Provider 配置

```env
OCR_PROVIDER=fake
OCR_TIMEOUT_SECONDS=300

# 官方托管 PaddleOCR-VL-1.6
PADDLEOCR_ACCESS_TOKEN=<local .env only>
PADDLEOCR_API_JOB_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLEOCR_VL_MODEL=PaddleOCR-VL-1.6
PADDLEOCR_API_REQUEST_TIMEOUT_SECONDS=30
PADDLEOCR_API_POLL_INTERVAL_SECONDS=5

# 本地 PaddleOCR 3.x 回退配置
PADDLEOCR_LANGUAGE=ch
PADDLEOCR_MODEL_NAME=PP-OCRv5_server_rec
```

只有一个 Provider 在应用组合阶段被选中。未知名称导致启动/请求配置错误，不自动回退到 Fake，避免教师误以为正在使用真实识别。

## 11. 未来兼容

- MinerU：把布局/公式/表格结果映射为 blocks，原始 JSON 保留；当前不接入完整文档/PDF 解析。
- Quark Yescan：当前作为独立的整页题目检测 Adapter，按一个 group-level `StructureInfo` 输出一个候选；它不属于本地 Paddle OCR 接口，也不把题内 Detail 拆成多题。未来若把 Yescan 另接为 OCR Provider，需独立契约。
- Doc2X：Markdown/LaTeX 作为标准文本或 block metadata；资源链接进入 raw response。
- 每个未来 Adapter 复用合约测试；接入第二个可用 Provider 时必须先创建 proposal。统一接口不等于自动路由授权。

## 12. 未来图像端口概念

`ImageGenerationProvider` 与 `DiagramProvider` 只作为 Roadmap 概念。它们未来也必须返回原始响应、派生图像 lineage 和教师审核状态；Phase 1 不创建接口或空实现。
