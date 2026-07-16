import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProblemIntake } from "./ProblemIntake";
import { ApiClientError } from "@/lib/contracts";
import { problemRecordFixture } from "@/test/problem-record-fixture";

const mocks = vi.hoisted(() => ({
  uploadAsset: vi.fn(),
  getAsset: vi.fn(),
  getAssetProblems: vi.fn(),
  detectProblemRegions: vi.fn(),
  createRegionsBatch: vi.fn(),
  runOCR: vi.fn(),
}));

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    uploadAsset: mocks.uploadAsset,
    getAsset: mocks.getAsset,
    getAssetProblems: mocks.getAssetProblems,
    detectProblemRegions: mocks.detectProblemRegions,
    createRegionsBatch: mocks.createRegionsBatch,
    runOCR: mocks.runOCR,
  };
});

const timestamp = "2026-07-12T08:00:00Z";

function candidate(
  index: number,
  y: number,
  options: {
    x?: number;
    width?: number;
    height?: number;
    metadata?: Record<string, string | boolean>;
  } = {},
) {
  const x = options.x ?? 60;
  const width = options.width ?? 480;
  const height = options.height ?? 120;
  return {
    detectionCandidateId: `candidate_${index}`,
    providerCandidateId: `fake-${index}`,
    coordinateSystem: "pixel_top_left",
    bbox: { x, y, width, height },
    normalizedBbox: { x: x / 600, y: y / 900, width: width / 600, height: height / 900 },
    confidence: 0.99,
    readingOrder: index - 1,
    metadata: options.metadata ?? { fixture: true },
  };
}

function detectionCandidates() {
  return [
    candidate(1, 120, {
      width: 330,
    }),
    candidate(2, 120, {
      x: 405,
      width: 135,
    }),
    candidate(3, 570),
  ];
}

describe("ProblemIntake multi-region workflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    const asset = {
      assetId: "asset_test",
      fileName: "worksheet.png",
      mediaType: "image/png",
      storageKey: "sources/asset_test.png",
      fileHash: "hash",
      width: 600,
      height: 900,
      fileSize: 100,
      contentUrl: "/api/v1/assets/asset_test/content",
      duplicateOfAssetId: null,
      createdAt: timestamp,
    };
    mocks.uploadAsset.mockResolvedValue(asset);
    mocks.getAsset.mockResolvedValue(asset);
    mocks.getAssetProblems.mockResolvedValue({ assetId: "asset_test", count: 0, items: [] });
    mocks.detectProblemRegions.mockResolvedValue({
      runId: "detection_test",
      provider: "fake",
      model: "deterministic-page-layout-v1",
      providerVersion: "1",
      status: "succeeded",
      errorCode: null,
      candidates: detectionCandidates(),
      warnings: [],
      startedAt: timestamp,
      finishedAt: timestamp,
      processingTimeMs: 1,
    });
    mocks.createRegionsBatch.mockResolvedValue({
      createdCount: 2,
      items: [
        {
          regionId: "region_1",
          problemId: "problem_1",
          coordinateSystem: "pixel_top_left",
          bbox: { x: 60, y: 120, width: 330, height: 120 },
          cropContentUrl: "/api/v1/regions/region_1/crop",
          selectionSource: "detected",
          detectionCandidateId: "candidate_1",
          detectionCandidateIds: ["candidate_1"],
          createdAt: timestamp,
        },
        {
          regionId: "region_3",
          problemId: "problem_3",
          coordinateSystem: "pixel_top_left",
          bbox: { x: 60, y: 570, width: 480, height: 120 },
          cropContentUrl: "/api/v1/regions/region_3/crop",
          selectionSource: "detected",
          detectionCandidateId: "candidate_3",
          detectionCandidateIds: ["candidate_3"],
          createdAt: timestamp,
        },
      ],
    });
    mocks.runOCR.mockResolvedValue({ provider: "fake" });
  });

  it("uploads only and starts manual boxing by default", async () => {
    const user = userEvent.setup();
    render(<ProblemIntake />);

    await user.upload(
      screen.getByLabelText("作业或试卷图片"),
      new File(["png"], "worksheet.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传并手动框题" }));

    expect(await screen.findByText("人工框题模式 · 自动框题可选")).toBeVisible();
    expect(screen.getByText("手动框题", { selector: ".canvas-mode-indicator" })).toBeVisible();
    expect(screen.getByText("在原图上拖拽，框出第一道错题。")).toBeVisible();
    expect(mocks.uploadAsset).toHaveBeenCalledTimes(1);
    expect(mocks.detectProblemRegions).not.toHaveBeenCalled();
  });

  it("auto-detects unselected boxes, supports click multi-select, and batch-saves only selected", async () => {
    const user = userEvent.setup();
    render(<ProblemIntake />);

    await user.upload(
      screen.getByLabelText("作业或试卷图片"),
      new File(["png"], "worksheet.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传并自动框题" }));

    expect(await screen.findByText("fake · 3/3 个候选题框")).toBeVisible();
    expect(screen.getByRole("heading", { name: "已选 0 道" })).toBeVisible();
    expect(screen.getByRole("button", { name: "完成选题 0 道" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "自动题目框 1，未选择" }));
    await user.click(screen.getByRole("button", { name: "自动题目框 3，未选择" }));

    expect(screen.getByRole("heading", { name: "已选 2 道" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "完成选题 2 道" }));

    await waitFor(() => expect(mocks.createRegionsBatch).toHaveBeenCalledTimes(1));
    const [first, , third] = detectionCandidates();
    expect(mocks.createRegionsBatch).toHaveBeenCalledWith("asset_test", {
      coordinateSystem: "normalized_top_left",
      regions: [
        {
          selectionSource: "detected",
          detectionCandidateIds: ["candidate_1"],
          bbox: first.normalizedBbox,
        },
        {
          selectionSource: "detected",
          detectionCandidateIds: ["candidate_3"],
          bbox: third.normalizedBbox,
        },
      ],
    });
    expect(await screen.findByRole("heading", { name: "已保存 2 道题" })).toBeVisible();
    expect(screen.getByLabelText("本次选题结果")).toHaveValue(
      "教师精选已完成，请继续处理以下题目：\nproblem_1\nproblem_3",
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(mocks.runOCR).not.toHaveBeenCalled();
  });

  it("lets the teacher merge two provider boxes when one question was split", async () => {
    const user = userEvent.setup();
    mocks.createRegionsBatch.mockResolvedValueOnce({
      createdCount: 1,
      items: [
        {
          regionId: "region_combined",
          problemId: "problem_combined",
          coordinateSystem: "pixel_top_left",
          bbox: { x: 60, y: 120, width: 480, height: 330 },
          cropContentUrl: "/api/v1/regions/region_combined/crop",
          selectionSource: "detected",
          detectionCandidateId: "candidate_1",
          detectionCandidateIds: ["candidate_1", "candidate_2"],
          createdAt: timestamp,
        },
      ],
    });
    render(<ProblemIntake />);

    await user.upload(
      screen.getByLabelText("作业或试卷图片"),
      new File(["png"], "worksheet.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传并自动框题" }));
    await user.click(await screen.findByRole("button", { name: "自动题目框 1，未选择" }));
    await user.click(screen.getByRole("button", { name: "自动题目框 2，未选择" }));

    expect(screen.getByRole("heading", { name: "已选 2 道" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "合并为一题" }));

    expect(screen.getByRole("heading", { name: "已选 1 道" })).toBeVisible();
    expect(screen.getByText("一道题（合并 2 个识别框）")).toBeVisible();
    expect(screen.getByText("fake · 3/3 个候选题框")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "完成选题 1 道" }));

    await waitFor(() => expect(mocks.createRegionsBatch).toHaveBeenCalledTimes(1));
    expect(mocks.createRegionsBatch).toHaveBeenCalledWith("asset_test", {
      coordinateSystem: "normalized_top_left",
      regions: [
        {
          selectionSource: "detected",
          detectionCandidateIds: ["candidate_1", "candidate_2"],
          bbox: { x: 0.1, y: 120 / 900, width: 0.8, height: 120 / 900 },
        },
      ],
    });
    expect(screen.getAllByText("一道题（合并 2 个识别框）")).toHaveLength(2);
    expect(await screen.findByRole("heading", { name: "已保存 1 道题" })).toBeVisible();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(mocks.runOCR).not.toHaveBeenCalled();
  });

  it("keeps manual boxing available when automatic detection fails", async () => {
    const user = userEvent.setup();
    mocks.detectProblemRegions.mockRejectedValueOnce(
      new ApiClientError({
        code: "region_detection_provider_unavailable",
        message: "自动框题暂不可用，仍可手动框题。",
        status: 503,
        retryable: true,
        requestId: "req_detection",
      }),
    );
    render(<ProblemIntake />);

    await user.upload(
      screen.getByLabelText("作业或试卷图片"),
      new File(["png"], "worksheet.png", { type: "image/png" }),
    );
    await user.click(screen.getByRole("button", { name: "上传并自动框题" }));

    expect(await screen.findByText("自动框题暂不可用，仍可手动框题。")).toBeVisible();
    expect(screen.getByText("手动框题", { selector: ".canvas-mode-indicator" })).toBeVisible();
    expect(screen.getByRole("button", { name: "手动框题" })).toBeEnabled();
    expect(screen.getByAltText("已上传的作业原图，叠加可选择的题目框")).toBeVisible();
  });

  it("loads an existing asset manual-first and returns problem IDs without running OCR", async () => {
    mocks.createRegionsBatch.mockResolvedValueOnce({
      createdCount: 1,
      items: [
        {
          regionId: "region_manual",
          problemId: "problem_manual",
          coordinateSystem: "pixel_top_left",
          bbox: { x: 60, y: 450, width: 480, height: 180 },
          cropContentUrl: "/api/v1/regions/region_manual/crop",
          selectionSource: "manual",
          detectionCandidateId: null,
          detectionCandidateIds: [],
          createdAt: timestamp,
        },
      ],
    });
    render(<ProblemIntake existingAssetId="asset_test" />);

    const surface = await screen.findByTestId("multi-region-surface");
    expect(screen.queryByLabelText("作业或试卷图片")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "自动框题" })).toBeEnabled();
    expect(mocks.getAsset).toHaveBeenCalledWith("asset_test", expect.any(AbortSignal));
    expect(mocks.detectProblemRegions).not.toHaveBeenCalled();
    expect(
      await screen.findByText("手动框题", { selector: ".canvas-mode-indicator" }),
    ).toBeVisible();

    Object.defineProperty(surface, "getBoundingClientRect", {
      value: () => ({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 600,
        bottom: 900,
        width: 600,
        height: 900,
        toJSON: () => ({}),
      }),
    });
    fireEvent.pointerDown(surface, { button: 0, pointerId: 1, clientX: 60, clientY: 450 });
    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 540, clientY: 630 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 540, clientY: 630 });

    expect(screen.getByRole("heading", { name: "已选 1 道" })).toBeVisible();
    await userEvent.setup().click(
      screen.getByRole("button", { name: "完成选题 1 道" }),
    );

    expect(await screen.findByRole("heading", { name: "已保存 1 道题" })).toBeVisible();
    expect(mocks.runOCR).not.toHaveBeenCalled();
    expect(screen.getByLabelText("本次选题结果")).toHaveValue(
      "教师精选已完成，请继续处理以下题目：\nproblem_manual",
    );
  });

  it("lets an existing-asset handoff explicitly request automatic boxes", async () => {
    const user = userEvent.setup();
    render(<ProblemIntake existingAssetId="asset_test" />);

    await user.click(await screen.findByRole("button", { name: "自动框题" }));

    expect(mocks.detectProblemRegions).toHaveBeenCalledWith("asset_test");
    expect(await screen.findByText("fake · 3/3 个候选题框")).toBeVisible();
  });

  it("returns from completion to an add-only pass and accumulates the saved results", async () => {
    const user = userEvent.setup();
    const record = problemRecordFixture({
      source: {
        ...problemRecordFixture().source,
        assetId: "asset_test",
        width: 600,
        height: 900,
      },
      region: {
        ...problemRecordFixture().region,
        regionId: "region_saved",
        bbox: { x: 60, y: 450, width: 480, height: 180 },
        selectionSource: "manual",
        detectionCandidateId: null,
        detectionCandidateIds: [],
      },
      lineage: {
        sourceAssetId: "asset_test",
        problemRegionId: "region_saved",
        detectionCandidateId: null,
        detectionCandidateIds: [],
        ocrRunId: "ocr_test",
        revisionId: null,
      },
    });
    const addedRecord = problemRecordFixture({
      problemId: "problem_added",
      source: record.source,
      region: {
        ...record.region,
        regionId: "region_added",
        bbox: { x: 60, y: 90, width: 480, height: 180 },
        croppedAssetKey: "crops/region_added/problem.png",
        cropContentUrl: "/api/v1/regions/region_added/crop",
      },
      lineage: {
        ...record.lineage,
        problemRegionId: "region_added",
      },
    });
    mocks.getAssetProblems
      .mockResolvedValueOnce({
        assetId: "asset_test",
        count: 1,
        items: [record],
      })
      .mockResolvedValueOnce({
        assetId: "asset_test",
        count: 2,
        items: [record, addedRecord],
      });
    mocks.createRegionsBatch.mockResolvedValueOnce({
      createdCount: 1,
      items: [
        {
          regionId: "region_added",
          problemId: "problem_added",
          coordinateSystem: "pixel_top_left",
          bbox: { x: 60, y: 90, width: 480, height: 180 },
          cropContentUrl: "/api/v1/regions/region_added/crop",
          selectionSource: "manual",
          detectionCandidateId: null,
          detectionCandidateIds: [],
          createdAt: timestamp,
        },
      ],
    });

    render(<ProblemIntake existingAssetId="asset_test" />);

    expect(await screen.findByRole("heading", { name: "本页选题已完成" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "已保存 1 道" })).toBeVisible();
    expect(screen.getByRole("button", { name: "手动题目框 1，已选择" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
    expect(screen.getByRole("button", { name: "已完成选题 1 道" })).toBeDisabled();
    expect(screen.getByLabelText("本次选题结果")).toHaveValue(
      "教师精选已完成，请继续处理以下题目：\nproblem_test",
    );
    await user.click(screen.getByRole("button", { name: "返回框题，继续补选" }));

    expect(screen.getByRole("heading", { name: "回到原图，补选漏掉的题" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "本轮已选 0 道" })).toBeVisible();
    expect(screen.getByRole("img", { name: "已保存手动题目框 1" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "已保存 1 道题" })).not.toBeInTheDocument();
    expect(screen.getByText("此前已保存 1 道（灰框） · 人工框题模式 · 自动框题可选")).toBeVisible();

    const surface = screen.getByTestId("multi-region-surface");
    Object.defineProperty(surface, "getBoundingClientRect", {
      value: () => ({
        x: 0,
        y: 0,
        left: 0,
        top: 0,
        right: 600,
        bottom: 900,
        width: 600,
        height: 900,
        toJSON: () => ({}),
      }),
    });
    fireEvent.pointerDown(surface, { button: 0, pointerId: 1, clientX: 60, clientY: 90 });
    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 540, clientY: 270 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 540, clientY: 270 });

    expect(screen.getByRole("heading", { name: "本轮已选 1 道" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "完成选题 1 道" }));

    await waitFor(() => expect(mocks.createRegionsBatch).toHaveBeenCalledTimes(1));
    expect(mocks.createRegionsBatch).toHaveBeenCalledWith("asset_test", {
      coordinateSystem: "normalized_top_left",
      regions: [
        {
          selectionSource: "manual",
          detectionCandidateIds: [],
          bbox: {
            x: 0.1,
            y: 0.1,
            width: 0.8,
            height: 0.19999999999999998,
          },
        },
      ],
    });
    expect(await screen.findByRole("heading", { name: "已保存 2 道题" })).toBeVisible();
    expect(screen.getByLabelText("本次选题结果")).toHaveValue(
      "教师精选已完成，请继续处理以下题目：\nproblem_test\nproblem_added",
    );
    expect(mocks.runOCR).not.toHaveBeenCalled();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
