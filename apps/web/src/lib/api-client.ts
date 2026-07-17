import type {
  AssetProblemCollection,
  BatchRegionCreate,
  BatchRegionCreateRequest,
  NormalizedProblemRecord,
  OCRRun,
  ProblemPublication,
  ProblemRevision,
  RegionCreate,
  RegionCreateRequest,
  RegionDetectionRun,
  RevisionCreateRequest,
  SourceAsset,
} from "./contracts";
import { ApiClientError } from "./contracts";

const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1"
).replace(/\/$/, "");

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNonEmptyString(value: unknown): value is string {
  return isString(value) && value.length > 0;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isUniqueStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.every(isNonEmptyString) &&
    new Set(value).size === value.length
  );
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isNullableConfidence(value: unknown): value is number | null {
  return (
    value === null ||
    (typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1)
  );
}

function isJsonValue(value: unknown): boolean {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  ) {
    return true;
  }
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
}

function isTimestamp(value: unknown): value is string {
  return (
    isString(value) &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isNullableTimestamp(value: unknown): value is string | null {
  return value === null || isTimestamp(value);
}

function isEvidencePath(value: unknown): value is string {
  return isString(value) && value.startsWith("/api/v1/");
}

function isPublicationStatus(value: unknown): boolean {
  return value === "pending" || value === "succeeded" || value === "failed";
}

function isPixelBBox(value: unknown): boolean {
  return (
    isRecord(value) &&
    Number.isInteger(value.x) &&
    Number(value.x) >= 0 &&
    Number.isInteger(value.y) &&
    Number(value.y) >= 0 &&
    Number.isInteger(value.width) &&
    Number(value.width) > 0 &&
    Number.isInteger(value.height) &&
    Number(value.height) > 0
  );
}

function isNormalizedBBox(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const values = [value.x, value.y, value.width, value.height];
  if (!values.every((item) => typeof item === "number" && Number.isFinite(item))) {
    return false;
  }
  const x = Number(value.x);
  const y = Number(value.y);
  const width = Number(value.width);
  const height = Number(value.height);
  return (
    x >= 0 &&
    y >= 0 &&
    width > 0 &&
    height > 0 &&
    x + width <= 1.000001 &&
    y + height <= 1.000001
  );
}

function isRegionSelectionSource(value: unknown): value is "manual" | "detected" {
  return value === "manual" || value === "detected";
}

function hasValidSelectionLineage(value: Record<string, unknown>): boolean {
  if (
    !isRegionSelectionSource(value.selectionSource) ||
    !isNullableString(value.detectionCandidateId) ||
    !isUniqueStringArray(value.detectionCandidateIds)
  ) {
    return false;
  }
  if (value.selectionSource === "manual") {
    return value.detectionCandidateId === null && value.detectionCandidateIds.length === 0;
  }
  return (
    value.detectionCandidateIds.length > 0 &&
    value.detectionCandidateId === value.detectionCandidateIds[0]
  );
}

function isOCRBlock(value: unknown): boolean {
  return (
    isRecord(value) &&
    (value.type === "text" ||
      value.type === "formula" ||
      value.type === "table" ||
      value.type === "diagram" ||
      value.type === "unknown") &&
    isString(value.text) &&
    (value.bbox === null || isPixelBBox(value.bbox)) &&
    isNullableConfidence(value.confidence) &&
    Number.isInteger(value.readingOrder) &&
    Number(value.readingOrder) >= 0 &&
    isRecord(value.metadata) &&
    Object.values(value.metadata).every(isJsonValue)
  );
}

function isSourceAsset(value: unknown): value is SourceAsset {
  return (
    isRecord(value) &&
    isNonEmptyString(value.assetId) &&
    isString(value.fileName) &&
    (value.mediaType === "image/jpeg" || value.mediaType === "image/png") &&
    isString(value.storageKey) &&
    isString(value.fileHash) &&
    Number.isInteger(value.width) &&
    Number(value.width) > 0 &&
    Number.isInteger(value.height) &&
    Number(value.height) > 0 &&
    Number.isInteger(value.fileSize) &&
    Number(value.fileSize) > 0 &&
    isEvidencePath(value.contentUrl) &&
    isTimestamp(value.createdAt) &&
    (value.duplicateOfAssetId === undefined || isNullableString(value.duplicateOfAssetId))
  );
}

function isRegionCreate(value: unknown): value is RegionCreate {
  return (
    isRecord(value) &&
    isNonEmptyString(value.regionId) &&
    isNonEmptyString(value.problemId) &&
    value.coordinateSystem === "pixel_top_left" &&
    isPixelBBox(value.bbox) &&
    isEvidencePath(value.cropContentUrl) &&
    hasValidSelectionLineage(value) &&
    isTimestamp(value.createdAt)
  );
}

function isRegionCandidate(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNonEmptyString(value.detectionCandidateId) &&
    isNonEmptyString(value.providerCandidateId) &&
    value.coordinateSystem === "pixel_top_left" &&
    isPixelBBox(value.bbox) &&
    isNormalizedBBox(value.normalizedBbox) &&
    isNullableConfidence(value.confidence) &&
    Number.isInteger(value.readingOrder) &&
    Number(value.readingOrder) >= 0 &&
    isRecord(value.metadata) &&
    Object.values(value.metadata).every(isJsonValue)
  );
}

function isRegionDetectionRun(value: unknown): value is RegionDetectionRun {
  return (
    isRecord(value) &&
    isNonEmptyString(value.runId) &&
    isNonEmptyString(value.provider) &&
    isNullableString(value.model) &&
    isNullableString(value.providerVersion) &&
    value.status === "succeeded" &&
    value.errorCode === null &&
    Array.isArray(value.candidates) &&
    value.candidates.every(isRegionCandidate) &&
    Array.isArray(value.warnings) &&
    value.warnings.every(isString) &&
    isTimestamp(value.startedAt) &&
    isTimestamp(value.finishedAt) &&
    Number.isInteger(value.processingTimeMs) &&
    Number(value.processingTimeMs) >= 0
  );
}

function isBatchRegionCreate(value: unknown): value is BatchRegionCreate {
  return (
    isRecord(value) &&
    Number.isInteger(value.createdCount) &&
    Number(value.createdCount) > 0 &&
    Array.isArray(value.items) &&
    value.items.length === value.createdCount &&
    value.items.every(isRegionCreate)
  );
}

function isOCRRun(value: unknown): value is OCRRun {
  return (
    isRecord(value) &&
    isNonEmptyString(value.runId) &&
    isNonEmptyString(value.provider) &&
    isNullableString(value.model) &&
    isNullableString(value.providerVersion) &&
    isNullableString(value.text) &&
    isNullableConfidence(value.confidence) &&
    (value.status === "running" || value.status === "succeeded" || value.status === "failed") &&
    Array.isArray(value.blocks) &&
    value.blocks.every(isOCRBlock) &&
    (value.rawResponse === null || isJsonValue(value.rawResponse)) &&
    Array.isArray(value.warnings) &&
    value.warnings.every(isString) &&
    isNullableString(value.errorCode) &&
    isNullableNumber(value.processingTimeMs) &&
    isTimestamp(value.startedAt) &&
    isNullableTimestamp(value.finishedAt)
  );
}

function isRevision(value: unknown): value is ProblemRevision {
  return (
    isRecord(value) &&
    isNonEmptyString(value.revisionId) &&
    isNonEmptyString(value.basedOnOcrRunId) &&
    Number.isInteger(value.revisionNumber) &&
    Number(value.revisionNumber) > 0 &&
    isNonEmptyString(value.correctedText) &&
    isNullableString(value.correctionNote) &&
    isTimestamp(value.createdAt)
  );
}

function isProblemRegion(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNonEmptyString(value.regionId) &&
    Number.isInteger(value.pageNumber) &&
    Number(value.pageNumber) > 0 &&
    isPixelBBox(value.bbox) &&
    value.coordinateSystem === "pixel_top_left" &&
    isString(value.croppedAssetKey) &&
    isEvidencePath(value.cropContentUrl) &&
    hasValidSelectionLineage(value) &&
    isTimestamp(value.createdAt)
  );
}

function isLineage(value: unknown): boolean {
  return (
    isRecord(value) &&
    isNonEmptyString(value.sourceAssetId) &&
    isNonEmptyString(value.problemRegionId) &&
    isNullableString(value.detectionCandidateId) &&
    isUniqueStringArray(value.detectionCandidateIds) &&
    (value.detectionCandidateIds.length === 0
      ? value.detectionCandidateId === null
      : value.detectionCandidateId === value.detectionCandidateIds[0]) &&
    isNullableString(value.ocrRunId) &&
    isNullableString(value.revisionId)
  );
}

function isHistory(value: unknown): boolean {
  return (
    isRecord(value) &&
    Array.isArray(value.ocrRuns) &&
    value.ocrRuns.every(isOCRRun) &&
    Array.isArray(value.revisions) &&
    value.revisions.every(isRevision)
  );
}

function isPublication(value: unknown): value is ProblemPublication {
  return (
    isRecord(value) &&
    isNonEmptyString(value.publicationId) &&
    isNonEmptyString(value.publisher) &&
    isPublicationStatus(value.status) &&
    isNonEmptyString(value.publishedRevisionId) &&
    isNonEmptyString(value.baseName) &&
    isNullableString(value.pagesTableId) &&
    isNullableString(value.questionsTableId) &&
    isNullableString(value.pageRecordId) &&
    isNullableString(value.questionRecordId) &&
    isNullableString(value.errorCode) &&
    typeof value.retryable === "boolean" &&
    isTimestamp(value.startedAt) &&
    isNullableTimestamp(value.finishedAt) &&
    isTimestamp(value.updatedAt)
  );
}

function isProblemRecord(value: unknown): value is NormalizedProblemRecord {
  return (
    isRecord(value) &&
    isNonEmptyString(value.problemId) &&
    isSourceAsset(value.source) &&
    isProblemRegion(value.region) &&
    isLineage(value.lineage) &&
    isHistory(value.history) &&
    (value.ocr === null || isOCRRun(value.ocr)) &&
    (value.latestOcrRun === null || isOCRRun(value.latestOcrRun)) &&
    (value.humanRevision === null || isRevision(value.humanRevision)) &&
    (value.publication === null || isPublication(value.publication)) &&
    isTimestamp(value.createdAt) &&
    isTimestamp(value.updatedAt)
  );
}

function isAssetProblemCollection(value: unknown): value is AssetProblemCollection {
  return (
    isRecord(value) &&
    isNonEmptyString(value.assetId) &&
    Number.isInteger(value.count) &&
    Number(value.count) >= 0 &&
    Array.isArray(value.items) &&
    value.items.length === value.count &&
    value.items.every(isProblemRecord) &&
    value.items.every((item) => item.source.assetId === value.assetId)
  );
}

export function decodeApiError(
  payload: unknown,
  status: number,
  responseRequestId: string | null = null,
): ApiClientError {
  if (isRecord(payload) && isRecord(payload.error)) {
    const error = payload.error;
    const details = isRecord(error.details) ? error.details : {};
    return new ApiClientError({
      code: isString(error.code) ? error.code : "request_failed",
      message: isString(error.message) ? error.message : "操作失败，请稍后重试。",
      status,
      retryable: error.retryable === true,
      requestId: isString(error.requestId) ? error.requestId : responseRequestId,
      details,
    });
  }
  return new ApiClientError({
    code: "request_failed",
    message: "服务返回了无法识别的错误，请稍后重试。",
    status,
    requestId: responseRequestId,
  });
}

export function asApiError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) {
    return error;
  }
  return new ApiClientError({
    code: "network_error",
    message: "无法连接到服务，请确认 API 已启动后重试。",
    status: 0,
    retryable: true,
  });
}

async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });
  let payload: unknown = null;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    payload = await response.json();
  }
  if (!response.ok) {
    throw decodeApiError(payload, response.status, response.headers.get("x-request-id"));
  }
  return payload;
}

function invalidResponse(): never {
  throw new ApiClientError({
    code: "invalid_response",
    message: "服务返回的数据不完整，请刷新后重试。",
    status: 502,
    retryable: true,
  });
}

export function mediaUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return new URL(path, `${API_BASE_URL}/`).toString();
}

export async function uploadAsset(file: File): Promise<SourceAsset> {
  const form = new FormData();
  form.append("file", file);
  const payload = await requestJson("/assets", { method: "POST", body: form });
  return isSourceAsset(payload) ? payload : invalidResponse();
}

export async function getAsset(assetId: string, signal?: AbortSignal): Promise<SourceAsset> {
  const payload = await requestJson(`/assets/${encodeURIComponent(assetId)}`, { signal });
  return isSourceAsset(payload) ? payload : invalidResponse();
}

export async function getAssetProblems(
  assetId: string,
  signal?: AbortSignal,
): Promise<AssetProblemCollection> {
  const payload = await requestJson(`/assets/${encodeURIComponent(assetId)}/problems`, {
    signal,
  });
  return isAssetProblemCollection(payload) ? payload : invalidResponse();
}

export async function createRegion(
  assetId: string,
  request: RegionCreateRequest,
): Promise<RegionCreate> {
  const payload = await requestJson(`/assets/${encodeURIComponent(assetId)}/regions`, {
    method: "POST",
    body: JSON.stringify(request),
  });
  return isRegionCreate(payload) ? payload : invalidResponse();
}

export async function detectProblemRegions(assetId: string): Promise<RegionDetectionRun> {
  const payload = await requestJson(
    `/assets/${encodeURIComponent(assetId)}/detection-runs`,
    { method: "POST" },
  );
  return isRegionDetectionRun(payload) ? payload : invalidResponse();
}

export async function createRegionsBatch(
  assetId: string,
  request: BatchRegionCreateRequest,
): Promise<BatchRegionCreate> {
  const payload = await requestJson(`/assets/${encodeURIComponent(assetId)}/regions/batch`, {
    method: "POST",
    body: JSON.stringify(request),
  });
  return isBatchRegionCreate(payload) ? payload : invalidResponse();
}

export async function runOCR(regionId: string): Promise<OCRRun> {
  const payload = await requestJson(`/regions/${encodeURIComponent(regionId)}/ocr-runs`, {
    method: "POST",
  });
  return isOCRRun(payload) ? payload : invalidResponse();
}

export async function createRevision(
  regionId: string,
  request: RevisionCreateRequest,
): Promise<ProblemRevision> {
  const payload = await requestJson(`/regions/${encodeURIComponent(regionId)}/revisions`, {
    method: "POST",
    body: JSON.stringify(request),
  });
  return isRevision(payload) ? payload : invalidResponse();
}

export async function publishProblem(problemId: string): Promise<ProblemPublication> {
  const payload = await requestJson(
    `/problems/${encodeURIComponent(problemId)}/publications/lark`,
    { method: "POST" },
  );
  return isPublication(payload) ? payload : invalidResponse();
}

export async function getProblem(
  problemId: string,
  signal?: AbortSignal,
): Promise<NormalizedProblemRecord> {
  const payload = await requestJson(`/problems/${encodeURIComponent(problemId)}`, { signal });
  return isProblemRecord(payload) ? payload : invalidResponse();
}
