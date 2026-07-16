from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, Request, Response, UploadFile, status
from sqlalchemy import text

from mistake_notebook_api.api.runtime import Runtime
from mistake_notebook_api.api.schemas import (
    AssetProblemCollectionResponse,
    BatchRegionCreateRequest,
    BatchRegionCreateResponse,
    ErrorEnvelope,
    HealthResponse,
    NormalizedProblemResponse,
    OCRRunResponse,
    ProblemPublicationResponse,
    ProblemRevisionResponse,
    RegionCreateRequest,
    RegionCreateResponse,
    RegionDetectionRunResponse,
    ReviewRequest,
    RevisionCreateRequest,
    SourceAssetResponse,
)
from mistake_notebook_api.application.images import NormalizedBoundingBox
from mistake_notebook_api.application.services import RegionSelectionInput

_ERROR_DESCRIPTIONS = {
    400: "HTTP 请求或上传表单格式错误。",
    404: "找不到请求的来源材料或题目记录。",
    409: "当前状态不允许执行这个操作。",
    413: "上传图片超过系统允许的大小。",
    415: "上传文件不是支持的图片格式。",
    422: "请求内容没有通过校验。",
    500: "系统内部或本地文件存储发生错误。",
    502: "外部识别服务返回了无法解析的结果。",
    503: "识别或发布服务暂时不可用，或尚未正确配置。",
    504: "外部识别服务运行超时。",
}


def _error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        status_code: {
            "model": ErrorEnvelope,
            "description": _ERROR_DESCRIPTIONS[status_code],
        }
        for status_code in status_codes
    }


router = APIRouter(prefix="/api/v1", responses=_error_responses(400, 422, 500))


def _runtime(request: Request) -> Runtime:
    runtime: Runtime = request.app.state.runtime
    return runtime


@router.post(
    "/assets",
    status_code=status.HTTP_201_CREATED,
    summary="上传一张作业或试卷图片",
    tags=["来源图片"],
    responses=_error_responses(413, 415),
)
def upload_asset(
    request: Request, file: Annotated[UploadFile, File(description="JPG、JPEG 或 PNG 图片")]
) -> SourceAssetResponse:
    runtime = _runtime(request)
    data = file.file.read(runtime.settings.max_upload_bytes + 1)
    result = runtime.asset_service().upload(file_name=file.filename, data=data)
    return SourceAssetResponse.from_entity(
        result.asset, duplicate_of_asset_id=result.duplicate_of_asset_id
    )


@router.get(
    "/assets/{asset_id}",
    summary="读取来源图片元数据",
    tags=["来源图片"],
    responses=_error_responses(404),
)
def get_asset(request: Request, asset_id: str) -> SourceAssetResponse:
    return SourceAssetResponse.from_entity(_runtime(request).asset_service().get(asset_id))


@router.get(
    "/assets/{asset_id}/problems",
    response_model=AssetProblemCollectionResponse,
    summary="读取这张来源页中的全部错题",
    tags=["题目审核"],
    responses=_error_responses(404),
)
def list_asset_problems(
    request: Request, response: Response, asset_id: str
) -> AssetProblemCollectionResponse:
    views = _runtime(request).problem_service().list_records_for_asset(asset_id)
    response.headers["Cache-Control"] = "no-store"
    return AssetProblemCollectionResponse.from_views(asset_id, views)


@router.get(
    "/assets/{asset_id}/content",
    response_class=Response,
    summary="读取来源图片内容",
    tags=["来源图片"],
    responses=_error_responses(404),
)
def get_asset_content(request: Request, asset_id: str) -> Response:
    asset, data = _runtime(request).asset_service().content(asset_id)
    return Response(
        content=data,
        media_type=asset.media_type,
        headers={
            "ETag": f'"{asset.file_hash}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post(
    "/assets/{asset_id}/detection-runs",
    status_code=status.HTTP_201_CREATED,
    summary="可选：自动检测题目候选框",
    tags=["题目录入"],
    responses=_error_responses(404, 502, 503, 504),
)
def create_detection_run(request: Request, asset_id: str) -> RegionDetectionRunResponse:
    view = _runtime(request).region_detection_service().detect(asset_id)
    return RegionDetectionRunResponse.from_view(view)


@router.post(
    "/assets/{asset_id}/regions",
    status_code=status.HTTP_201_CREATED,
    summary="保存一个人工题目框",
    tags=["题目录入"],
    responses=_error_responses(404),
)
def create_region(
    request: Request, asset_id: str, payload: RegionCreateRequest
) -> RegionCreateResponse:
    bbox = payload.bbox
    result = (
        _runtime(request)
        .problem_service()
        .create_region(
            asset_id=asset_id,
            normalized_bbox=NormalizedBoundingBox(bbox.x, bbox.y, bbox.width, bbox.height),
        )
    )
    return RegionCreateResponse.from_result(result)


@router.post(
    "/assets/{asset_id}/regions/batch",
    status_code=status.HTTP_201_CREATED,
    summary="批量保存教师确认的题目框",
    tags=["题目录入"],
    responses=_error_responses(404, 409),
)
def create_regions_batch(
    request: Request,
    asset_id: str,
    payload: BatchRegionCreateRequest,
) -> BatchRegionCreateResponse:
    result = (
        _runtime(request)
        .problem_service()
        .create_regions_batch(
            asset_id=asset_id,
            selections=[
                RegionSelectionInput(
                    selection_source=item.selection_source,
                    normalized_bbox=NormalizedBoundingBox(
                        item.bbox.x,
                        item.bbox.y,
                        item.bbox.width,
                        item.bbox.height,
                    ),
                    detection_candidate_ids=item.detection_candidate_ids,
                )
                for item in payload.regions
            ],
        )
    )
    return BatchRegionCreateResponse.from_result(result)


@router.get(
    "/regions/{region_id}/crop",
    response_class=Response,
    summary="读取题目裁图",
    tags=["题目录入"],
    responses=_error_responses(404),
)
def get_region_crop(request: Request, region_id: str) -> Response:
    _, data = _runtime(request).problem_service().crop_content(region_id)
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post(
    "/regions/{region_id}/ocr-runs",
    status_code=status.HTTP_201_CREATED,
    summary="新增一次 OCR 识别",
    tags=["OCR 与修订"],
    responses=_error_responses(404, 502, 503, 504),
)
def create_ocr_run(request: Request, region_id: str) -> OCRRunResponse:
    run = _runtime(request).problem_service().run_ocr(region_id)
    return OCRRunResponse.from_entity(run)


@router.post(
    "/regions/{region_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    summary="保存一个新的教师修订版本",
    tags=["OCR 与修订"],
    responses=_error_responses(404),
)
def create_revision(
    request: Request, region_id: str, payload: RevisionCreateRequest
) -> ProblemRevisionResponse:
    revision = (
        _runtime(request)
        .problem_service()
        .create_revision(
            region_id=region_id,
            based_on_ocr_run_id=payload.based_on_ocr_run_id,
            corrected_text=payload.corrected_text,
            correction_note=payload.correction_note,
        )
    )
    return ProblemRevisionResponse.from_entity(revision)


@router.post(
    "/problems/{problem_id}/review",
    summary="确认一个教师修订为已审核题目",
    tags=["题目审核"],
    responses=_error_responses(404, 409),
)
def review_problem(
    request: Request, problem_id: str, payload: ReviewRequest
) -> NormalizedProblemResponse:
    view = (
        _runtime(request)
        .problem_service()
        .review(problem_id=problem_id, revision_id=payload.revision_id)
    )
    return NormalizedProblemResponse.from_view(view)


@router.post(
    "/problems/{problem_id}/publications/lark",
    response_model=ProblemPublicationResponse,
    summary="把已审核题目发布到飞书 Base",
    tags=["飞书 Base"],
    responses=_error_responses(404, 409, 502, 503, 504),
)
def publish_problem(request: Request, problem_id: str) -> ProblemPublicationResponse:
    publication = _runtime(request).publication_service().publish(problem_id)
    return ProblemPublicationResponse.from_entity(publication)


@router.get(
    "/problems/{problem_id}",
    response_model=NormalizedProblemResponse,
    summary="读取一条完整的规范化题目记录",
    tags=["题目审核"],
    responses=_error_responses(404),
)
def get_problem(request: Request, response: Response, problem_id: str) -> NormalizedProblemResponse:
    view = _runtime(request).problem_service().get_record(problem_id)
    response.headers["Cache-Control"] = "no-store"
    return NormalizedProblemResponse.from_view(view)


@router.get("/health", summary="检查系统与 Provider 状态", tags=["系统状态"])
def health(request: Request) -> HealthResponse:
    runtime = _runtime(request)
    with runtime.engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        database="ok",
        ocr_provider=runtime.ocr_provider.name,
        region_detection_provider=runtime.region_detection_provider.name,
    )
