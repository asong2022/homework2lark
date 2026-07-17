import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createRegionsBatch,
  decodeApiError,
  detectProblemRegions,
  getAssetProblems,
  getProblem,
  mediaUrl,
  publishProblem,
} from "./api-client";
import { problemRecordFixture } from "@/test/problem-record-fixture";

describe("api client boundary", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves stable API errors and request IDs", () => {
    const error = decodeApiError(
      {
        error: {
          code: "ocr_provider_unavailable",
          message: "OCR 服务暂不可用，原图和题目区域已经保留。",
          retryable: true,
          requestId: "req_test",
        },
      },
      503,
    );

    expect(error.code).toBe("ocr_provider_unavailable");
    expect(error.retryable).toBe(true);
    expect(error.requestId).toBe("req_test");
  });

  it("resolves evidence links against the configured API prefix", () => {
    expect(mediaUrl("/api/v1/assets/asset_test/content")).toBe(
      "http://localhost:8000/api/v1/assets/asset_test/content",
    );
  });

  it("rejects malformed nested success payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            problemId: "problem_test",
            source: {},
            region: {},
            lineage: {},
            history: {},
            ocr: null,
            latestOcrRun: null,
            humanRevision: null,
            createdAt: "now",
            updatedAt: "now",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(getProblem("problem_test")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("decodes a source-page problem collection and verifies every source ID", async () => {
    const record = problemRecordFixture();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ assetId: "asset_test", count: 1, items: [record] }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(getAssetProblems("asset_test")).resolves.toMatchObject({
      assetId: "asset_test",
      count: 1,
      items: [{ problemId: "problem_test" }],
    });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            assetId: "asset_other",
            count: 1,
            items: [record],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );
    await expect(getAssetProblems("asset_other")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("decodes a successful publication response", async () => {
    const publication = {
      publicationId: "publication_test",
      publisher: "fake",
      status: "succeeded",
      publishedRevisionId: "revision_test",
      baseName: "小学数学错题学习库",
      pagesTableId: "tbl_pages",
      questionsTableId: "tbl_questions",
      pageRecordId: "rec_page",
      questionRecordId: "rec_question",
      errorCode: null,
      retryable: false,
      startedAt: "2026-07-13T08:00:00Z",
      finishedAt: "2026-07-13T08:00:01Z",
      updatedAt: "2026-07-13T08:00:01Z",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(publication), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(publishProblem("problem_test")).resolves.toEqual(publication);
  });

  it("rejects malformed publication state inside a problem record", async () => {
    const valid = problemRecordFixture();
    const malformed = {
      ...valid,
      publication: {
        publicationId: "publication_test",
        status: "success",
      },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(malformed), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(getProblem("problem_test")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("rejects malformed OCR blocks inside an otherwise valid record", async () => {
    const valid = problemRecordFixture();
    const malformed = {
      ...valid,
      ocr: valid.ocr ? { ...valid.ocr, blocks: [null] } : null,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(malformed), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(getProblem("problem_test")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("rejects an external evidence URL in a Phase 1 record", async () => {
    const valid = problemRecordFixture();
    const malformed = {
      ...valid,
      source: { ...valid.source, contentUrl: "https://unexpected.example/student.png" },
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(malformed), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(getProblem("problem_test")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("decodes a logical problem backed by multiple Provider candidate boxes", async () => {
    const candidateIds = ["candidate_text", "candidate_diagram"];
    const valid = problemRecordFixture({
      region: {
        ...problemRecordFixture().region,
        selectionSource: "detected",
        detectionCandidateId: candidateIds[0],
        detectionCandidateIds: candidateIds,
      },
      lineage: {
        ...problemRecordFixture().lineage,
        detectionCandidateId: candidateIds[0],
        detectionCandidateIds: candidateIds,
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(valid), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(getProblem("problem_test")).resolves.toMatchObject({
      region: { detectionCandidateIds: candidateIds },
      lineage: { detectionCandidateIds: candidateIds },
    });
  });

  it("rejects a non-ISO timestamp before the detail formatter sees it", async () => {
    const valid = problemRecordFixture();
    const malformed = { ...valid, updatedAt: "07/12/2026" };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(malformed), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    await expect(getProblem("problem_test")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("decodes automatic candidates but rejects out-of-bounds normalized boxes", async () => {
    const candidate = {
      detectionCandidateId: "candidate_test",
      providerCandidateId: "provider-1",
      coordinateSystem: "pixel_top_left",
      bbox: { x: 10, y: 20, width: 80, height: 40 },
      normalizedBbox: { x: 0.1, y: 0.2, width: 0.8, height: 0.4 },
      confidence: 0.95,
      readingOrder: 0,
      metadata: {},
    };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            runId: "detection_test",
            provider: "fake",
            model: "fixture",
            providerVersion: "1",
            status: "succeeded",
            errorCode: null,
            candidates: [{ ...candidate, normalizedBbox: { ...candidate.normalizedBbox, x: 0.4 } }],
            warnings: [],
            startedAt: "2026-07-12T08:00:00Z",
            finishedAt: "2026-07-12T08:00:01Z",
            processingTimeMs: 1,
          }),
          { status: 201, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(detectProblemRegions("asset_test")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("rejects a batch response with inconsistent selection lineage", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            createdCount: 1,
            items: [
              {
                regionId: "region_test",
                problemId: "problem_test",
                coordinateSystem: "pixel_top_left",
                bbox: { x: 10, y: 20, width: 80, height: 40 },
                cropContentUrl: "/api/v1/regions/region_test/crop",
                selectionSource: "manual",
                detectionCandidateId: "candidate_should_be_null",
                detectionCandidateIds: ["candidate_should_be_null"],
                createdAt: "2026-07-12T08:00:00Z",
              },
            ],
          }),
          { status: 201, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    await expect(
      createRegionsBatch("asset_test", {
        coordinateSystem: "normalized_top_left",
        regions: [
          {
            selectionSource: "manual",
            detectionCandidateIds: [],
            bbox: { x: 0.1, y: 0.2, width: 0.8, height: 0.4 },
          },
        ],
      }),
    ).rejects.toMatchObject({ code: "invalid_response" });
  });
});
