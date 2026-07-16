import type { components } from "./generated-api";

export type SourceAsset = components["schemas"]["SourceAssetResponse"];
export type AssetProblemCollection = components["schemas"]["AssetProblemCollectionResponse"];
export type RegionCreate = components["schemas"]["RegionCreateResponse"];
export type BatchRegionCreate = components["schemas"]["BatchRegionCreateResponse"];
export type BatchRegionCreateRequest = components["schemas"]["BatchRegionCreateRequest"];
export type RegionDetectionRun = components["schemas"]["RegionDetectionRunResponse"];
export type RegionCandidate = components["schemas"]["RegionCandidateResponse"];
export type RegionSelectionRequest = components["schemas"]["RegionSelectionRequest"];
export type RegionSelectionSource = components["schemas"]["RegionSelectionSource"];
export type ProblemRegion = components["schemas"]["ProblemRegionResponse"];
export type OCRRun = components["schemas"]["OCRRunResponse"];
export type ProblemRevision = components["schemas"]["ProblemRevisionResponse"];
export type ProblemPublication = components["schemas"]["ProblemPublicationResponse"];
export type NormalizedProblemRecord = components["schemas"]["NormalizedProblemResponse"];
export type RegionCreateRequest = components["schemas"]["RegionCreateRequest"];
export type RevisionCreateRequest = components["schemas"]["RevisionCreateRequest"];
export type ReviewStatus = components["schemas"]["ReviewStatus"];

export type NormalizedBBox = RegionCreateRequest["bbox"];

export type RequestState<T> =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "success"; data: T }
  | { status: "error"; error: ApiClientError };

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly details: Record<string, unknown>;

  constructor(options: {
    code: string;
    message: string;
    status: number;
    retryable?: boolean;
    requestId?: string | null;
    details?: Record<string, unknown>;
  }) {
    super(options.message);
    this.name = "ApiClientError";
    this.code = options.code;
    this.status = options.status;
    this.retryable = options.retryable ?? false;
    this.requestId = options.requestId ?? null;
    this.details = options.details ?? {};
  }
}
