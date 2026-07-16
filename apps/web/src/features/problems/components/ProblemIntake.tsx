"use client";

/* eslint-disable @next/next/no-img-element -- Saved crop thumbnails come from the evidence API. */

import {
  CheckCheck,
  CircleOff,
  Clipboard,
  Combine,
  FileImage,
  Focus,
  LoaderCircle,
  Save,
  ScanLine,
  Trash2,
  Undo2,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import {
  MIN_NORMALIZED_REGION_SIZE,
  MultiRegionSelector,
  unionNormalizedBBoxes,
} from "./MultiRegionSelector";
import type { EditableRegion } from "./MultiRegionSelector";
import { useProblemIntake } from "../hooks/useProblemIntake";
import { mediaUrl } from "@/lib/api-client";
import type {
  AssetProblemCollection,
  NormalizedBBox,
  RegionDetectionRun,
  RequestState,
} from "@/lib/contracts";

const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png"]);

function StateError({ state }: { state: RequestState<unknown> }) {
  if (state.status !== "error") return null;
  return (
    <div className="error-panel compact-error" role="alert">
      <strong>这一步没有完成</strong>
      <p>{state.error.message}</p>
      {state.error.requestId ? <small>请求编号：{state.error.requestId}</small> : null}
    </div>
  );
}

export function editableRegionsFromDetection(run: RegionDetectionRun): EditableRegion[] {
  return [...run.candidates]
    .sort((left, right) => left.readingOrder - right.readingOrder)
    .map((candidate) => ({
      id: candidate.detectionCandidateId,
      detectionCandidateIds: [candidate.detectionCandidateId],
      source: "detected" as const,
      bbox: candidate.normalizedBbox,
      selected: false,
      readingOrder: candidate.readingOrder,
    }));
}

export function editableRegionsFromRecords(
  collection: AssetProblemCollection,
): EditableRegion[] {
  return collection.items.map((record, index) => ({
    id: record.region.regionId,
    detectionCandidateIds: record.region.detectionCandidateIds,
    source: record.region.selectionSource,
    bbox: {
      x: record.region.bbox.x / record.source.width,
      y: record.region.bbox.y / record.source.height,
      width: record.region.bbox.width / record.source.width,
      height: record.region.bbox.height / record.source.height,
    },
    selected: true,
    readingOrder: index,
  }));
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

function regionSourceLabel(region: EditableRegion): string {
  if (region.source === "manual") return "手动框题";
  if (region.detectionCandidateIds.length > 1) {
    return `一道题（合并 ${region.detectionCandidateIds.length} 个识别框）`;
  }
  return "自动题目框";
}

type ProblemIntakeProps = {
  existingAssetId?: string;
};

type UploadIntent = "manual" | "detect";

export function ProblemIntake({ existingAssetId }: ProblemIntakeProps = {}) {
  const handoffMode = Boolean(existingAssetId);
  const {
    assetState,
    collectionState,
    detectionState,
    batchState,
    upload,
    detect,
    saveRegions,
    refreshAssetProblems,
    resetBatch,
  } = useProblemIntake(existingAssetId);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [regions, setRegions] = useState<EditableRegion[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [manualMode, setManualMode] = useState(handoffMode);
  const [localError, setLocalError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");
  const [showSavedRegions, setShowSavedRegions] = useState(Boolean(existingAssetId));

  const persistedRegions = useMemo(
    () =>
      collectionState.status === "success"
        ? editableRegionsFromRecords(collectionState.data)
        : [],
    [collectionState],
  );
  const showingSavedCollection =
    showSavedRegions &&
    collectionState.status === "success" &&
    collectionState.data.count > 0;
  const completionMode =
    showSavedRegions && (batchState.status === "success" || showingSavedCollection);
  const supplementMode =
    !showSavedRegions &&
    collectionState.status === "success" &&
    collectionState.data.count > 0;
  const readOnlyRegionIds = useMemo(
    () =>
      supplementMode
        ? new Set(persistedRegions.map((region) => region.id))
        : undefined,
    [persistedRegions, supplementMode],
  );

  const displayedRegions = useMemo(
    () =>
      showingSavedCollection
        ? persistedRegions
        : supplementMode
          ? [...persistedRegions, ...regions]
          : regions,
    [persistedRegions, regions, showingSavedCollection, supplementMode],
  );

  const selectedRegions = useMemo(
    () =>
      [...(showingSavedCollection ? persistedRegions : regions)]
        .filter((region) => region.selected)
        .sort((left, right) =>
          left.bbox.y === right.bbox.y
            ? left.bbox.x - right.bbox.x
            : left.bbox.y - right.bbox.y,
        ),
    [persistedRegions, regions, showingSavedCollection],
  );
  const visibleDetectedCount = (showingSavedCollection ? persistedRegions : regions)
    .filter((item) => item.source === "detected")
    .reduce((count, item) => count + item.detectionCandidateIds.length, 0);
  const canMergeSelected =
    selectedRegions.length >= 2 &&
    selectedRegions.every(
      (region) => region.source === "detected" && region.detectionCandidateIds.length > 0,
    );
  const activeRegion = regions.find((region) => region.id === activeId) ?? null;
  const pending =
    assetState.status === "pending" ||
    collectionState.status === "pending" ||
    detectionState.status === "pending" ||
    batchState.status === "pending";
  const locked = completionMode;

  const applyDetection = (run: RegionDetectionRun) => {
    const manualRegions = regions.filter((region) => region.source === "manual");
    setRegions([...editableRegionsFromDetection(run), ...manualRegions]);
    setActiveId(null);
    setManualMode(false);
  };

  const handleUpload = async (
    event: FormEvent<HTMLFormElement> | null,
    intent: UploadIntent,
  ) => {
    event?.preventDefault();
    if (!selectedFile) {
      setLocalError("请先选择一张 JPG、JPEG 或 PNG 图片。");
      return;
    }
    if (!ACCEPTED_TYPES.has(selectedFile.type)) {
      setLocalError("当前只支持 JPG、JPEG 或 PNG 图片。");
      return;
    }
    setLocalError(null);
    setRegions([]);
    setActiveId(null);
    setManualMode(intent === "manual");
    setShowSavedRegions(false);
    try {
      const asset = await upload(selectedFile);
      if (intent === "manual") return;
      try {
        applyDetection(await detect(asset.assetId));
      } catch {
        setManualMode(true);
        // The source remains usable and manual boxing becomes the active fallback.
      }
    } catch {
      // The hook owns the teacher-facing upload error.
    }
  };

  const handleDetect = async () => {
    if (assetState.status !== "success") return;
    setLocalError(null);
    try {
      applyDetection(await detect(assetState.data.assetId));
    } catch {
      setManualMode(true);
      // Detection errors are rendered beside the image workspace.
    }
  };

  const handleSelectAll = () => {
    setRegions((current) => current.map((region) => ({ ...region, selected: true })));
  };

  const handleClearSelection = () => {
    setRegions((current) => current.map((region) => ({ ...region, selected: false })));
    setActiveId(null);
  };

  const handleDeleteActive = () => {
    if (!activeId) return;
    setRegions((current) => current.filter((region) => region.id !== activeId));
    setActiveId(null);
  };

  const handleMergeSelected = () => {
    if (!canMergeSelected) return;
    const selectedIds = new Set(selectedRegions.map((region) => region.id));
    const candidateIds = [
      ...new Set(selectedRegions.flatMap((region) => region.detectionCandidateIds)),
    ];
    const mergedId = `combined-${globalThis.crypto.randomUUID()}`;
    const mergedRegion: EditableRegion = {
      id: mergedId,
      detectionCandidateIds: candidateIds,
      source: "detected",
      bbox: unionNormalizedBBoxes(selectedRegions.map((region) => region.bbox)),
      selected: true,
      readingOrder: Math.min(...selectedRegions.map((region) => region.readingOrder)),
    };
    setRegions((current) => [
      ...current.filter((region) => !selectedIds.has(region.id)),
      mergedRegion,
    ]);
    setActiveId(mergedId);
    setManualMode(false);
    setLocalError(null);
  };

  const updateActiveCoordinate = (field: keyof NormalizedBBox, percentage: number) => {
    if (!activeId || !Number.isFinite(percentage)) return;
    setRegions((current) =>
      current.map((region) => {
        if (region.id !== activeId) return region;
        const normalized = clamp(percentage / 100);
        const next = { ...region.bbox, [field]: normalized };
        if (field === "x") next.x = Math.min(next.x, 1 - next.width);
        if (field === "y") next.y = Math.min(next.y, 1 - next.height);
        if (field === "width") {
          next.width = clamp(next.width, MIN_NORMALIZED_REGION_SIZE, 1 - next.x);
        }
        if (field === "height") {
          next.height = clamp(next.height, MIN_NORMALIZED_REGION_SIZE, 1 - next.y);
        }
        return { ...region, bbox: next };
      }),
    );
  };

  const handleSave = async () => {
    if (assetState.status !== "success" || selectedRegions.length === 0) {
      setLocalError("请先点击题目框，至少选择一道要保存的错题。");
      return;
    }
    setLocalError(null);
    try {
      await saveRegions(assetState.data.assetId, {
        coordinateSystem: "normalized_top_left",
        regions: selectedRegions.map((region) => ({
          selectionSource: region.source,
          detectionCandidateIds: region.detectionCandidateIds,
          bbox: region.bbox,
        })),
      });
      setShowSavedRegions(true);
      setCopyState("idle");
      await refreshAssetProblems(assetState.data.assetId);
      setActiveId(null);
      setManualMode(false);
    } catch {
      // The hook preserves the uploaded page, candidates, and teacher adjustments.
    }
  };

  const handleAddMore = () => {
    resetBatch();
    setShowSavedRegions(false);
    setRegions([]);
    setActiveId(null);
    setManualMode(true);
    setLocalError(null);
    setCopyState("idle");
  };

  const handleCancelSupplement = () => {
    resetBatch();
    setShowSavedRegions(true);
    setRegions([]);
    setActiveId(null);
    setManualMode(false);
    setLocalError(null);
    setCopyState("idle");
  };

  const currentErrorState: RequestState<unknown> =
    batchState.status === "error"
      ? batchState
      : collectionState.status === "error"
        ? collectionState
        : detectionState.status === "error"
          ? detectionState
          : assetState;

  const completedItems = useMemo(() => {
    if (!showSavedRegions) return [];
    if (collectionState.status === "success" && collectionState.data.count > 0) {
      return collectionState.data.items.map((record) => ({
        problemId: record.problemId,
        cropContentUrl: record.region.cropContentUrl,
        selectionSource: record.region.selectionSource,
        detectionCandidateIds: record.region.detectionCandidateIds,
      }));
    }
    if (batchState.status === "success") {
      return batchState.data.items.map((item) => ({
        problemId: item.problemId,
        cropContentUrl: item.cropContentUrl,
        selectionSource: item.selectionSource,
        detectionCandidateIds: item.detectionCandidateIds,
      }));
    }
    return [];
  }, [batchState, collectionState, showSavedRegions]);

  const detectorReadout =
    detectionState.status === "pending"
      ? "正在自动框题"
      : detectionState.status === "success"
        ? `${detectionState.data.provider} · ${visibleDetectedCount}/${detectionState.data.candidates.length} 个候选题框`
        : detectionState.status === "error"
          ? "自动框题不可用，可手动框题"
          : "人工框题模式 · 自动框题可选";
  const workspaceReadout = showingSavedCollection
    ? `已恢复 ${collectionState.data.count} 道已保存题目`
    : supplementMode
      ? `此前已保存 ${collectionState.data.count} 道（灰框） · ${detectorReadout}`
      : detectorReadout;

  const handoffText =
    completedItems.length > 0
      ? [
          "教师精选已完成，请继续处理以下题目：",
          ...completedItems.map((item) => item.problemId),
        ].join("\n")
      : "";

  const handleCopyHandoff = async () => {
    if (!handoffText) return;
    try {
      await navigator.clipboard.writeText(handoffText);
      setCopyState("copied");
      setLocalError(null);
    } catch {
      setLocalError("复制失败，请手动选中下方 problem ID 文本后复制。");
    }
  };

  return (
    <main className="page-shell intake-workbench">
      <header className="intake-command-header">
        <div>
          <p className="eyebrow">
            {completionMode
              ? "已保存的教师精选"
              : supplementMode
                ? "补选漏题"
                : handoffMode
                  ? "AI 对话接力"
                  : "教师精选"}
          </p>
          <h1>
            {completionMode
              ? "本页选题已完成"
              : supplementMode
                ? "回到原图，补选漏掉的题"
                : handoffMode
                  ? "从这页中选出要收录的题"
                  : "从整页作业中选出要保留的题"}
          </h1>
        </div>
        <div className="intake-stage" aria-live="polite">
          <span className={assetState.status === "success" ? "done" : "current"}>原图</span>
          <span className={displayedRegions.length > 0 ? "done" : "current"}>框题</span>
          <span className={completedItems.length > 0 ? "done" : "current"}>完成</span>
        </div>
      </header>

      <section className="upload-ribbon" aria-labelledby="upload-title">
        <div className="upload-ribbon-title">
          <FileImage size={20} aria-hidden="true" />
          <div>
            <h2 id="upload-title">作业或试卷原图</h2>
            {assetState.status === "success" ? (
              <p>
                {assetState.data.fileName} · {assetState.data.width} × {assetState.data.height}
              </p>
            ) : handoffMode ? (
              <p>正在读取 AI 对话中已上传的原图。</p>
            ) : (
              <p>JPG、JPEG 或 PNG；可手动框题，也可自动框题。</p>
            )}
          </div>
        </div>
        {handoffMode ? (
          <p className="handoff-source-note">
            {completionMode && collectionState.status === "success"
              ? `已恢复 ${collectionState.data.count} 道题，可直接把选题结果交回 AI。`
              : supplementMode
                ? `此前已保存 ${collectionState.data.count} 道；灰框只读，本轮只提交新框。`
              : "原图只上传一次；可手动框题，也可使用自动题目框。"}
          </p>
        ) : (
          <form
            className="compact-upload-form"
            onSubmit={(event) => void handleUpload(event, "manual")}
          >
            <label className="file-picker">
              <span>{selectedFile?.name ?? "选择图片"}</span>
              <input
                type="file"
                aria-label="作业或试卷图片"
                accept="image/jpeg,image/png,.jpg,.jpeg,.png"
                onChange={(event) => setSelectedFile(event.currentTarget.files?.[0] ?? null)}
                disabled={pending}
              />
            </label>
            <button className="button primary icon-button-label" type="submit" disabled={pending}>
              {assetState.status === "pending" ? (
                <LoaderCircle className="spin" size={18} aria-hidden="true" />
              ) : (
                <Focus size={18} aria-hidden="true" />
              )}
              {assetState.status === "pending"
                ? "正在上传"
                : assetState.status === "success"
                  ? "更换图片并手动框题"
                  : "上传并手动框题"}
            </button>
            <button
              className="button secondary icon-button-label"
              type="button"
              disabled={pending}
              onClick={() => void handleUpload(null, "detect")}
            >
              {detectionState.status === "pending" ? (
                <LoaderCircle className="spin" size={18} aria-hidden="true" />
              ) : (
                <ScanLine size={18} aria-hidden="true" />
              )}
              {detectionState.status === "pending"
                ? "正在自动框题"
                : assetState.status === "success"
                  ? "更换图片并自动框题"
                  : "上传并自动框题"}
            </button>
          </form>
        )}
      </section>

      {assetState.status === "success" ? (
        <section className="region-workspace" aria-label="题目框选工作区">
          <div className="region-canvas-column">
            <div className="region-toolbar" role="toolbar" aria-label="题目框工具">
              <button
                type="button"
                className="tool-button"
                onClick={handleDetect}
                disabled={pending || locked}
                title={detectionState.status === "idle" ? "调用自动框题" : "重新调用自动框题"}
              >
                {detectionState.status === "pending" ? (
                  <LoaderCircle className="spin" size={18} aria-hidden="true" />
                ) : (
                  <ScanLine size={18} aria-hidden="true" />
                )}
                <span>{detectionState.status === "idle" ? "自动框题" : "重新自动框题"}</span>
              </button>
              <button
                type="button"
                className="tool-button"
                onClick={handleSelectAll}
                disabled={pending || locked || regions.length === 0}
                title="选择本页全部候选"
              >
                <CheckCheck size={18} aria-hidden="true" />
                <span>全选</span>
              </button>
              <button
                type="button"
                className="tool-button"
                onClick={handleClearSelection}
                disabled={pending || locked || selectedRegions.length === 0}
                title="清空本页选择"
              >
                <CircleOff size={18} aria-hidden="true" />
                <span>清空</span>
              </button>
              <button
                type="button"
                className="tool-button"
                onClick={handleMergeSelected}
                disabled={pending || locked || !canMergeSelected}
                title="把误切开的题目框合并为一道题"
              >
                <Combine size={18} aria-hidden="true" />
                <span>合并为一题</span>
              </button>
              <button
                type="button"
                className={`tool-button${manualMode && !completionMode ? " active" : ""}`}
                onClick={() => setManualMode((current) => !current)}
                disabled={pending || locked}
                aria-pressed={manualMode && !completionMode}
                title="在原图上再画一个题目框"
              >
                <Focus size={18} aria-hidden="true" />
                <span>{displayedRegions.length > 0 ? "再框一题" : "手动框题"}</span>
              </button>
              <button
                type="button"
                className="tool-button danger"
                onClick={handleDeleteActive}
                disabled={pending || locked || !activeId}
                title="删除当前题目框"
              >
                <Trash2 size={18} aria-hidden="true" />
                <span>删除当前框</span>
              </button>
              <div className="detection-readout" aria-live="polite">
                {workspaceReadout}
              </div>
            </div>

            <div className="region-canvas-shell">
              <MultiRegionSelector
                imageUrl={mediaUrl(assetState.data.contentUrl)}
                regions={displayedRegions}
                activeId={activeId}
                manualMode={manualMode && !completionMode}
                readOnlyRegionIds={readOnlyRegionIds}
                onRegionsChange={(nextRegions) =>
                  setRegions(
                    readOnlyRegionIds
                      ? nextRegions.filter((region) => !readOnlyRegionIds.has(region.id))
                      : nextRegions,
                  )
                }
                onActiveChange={setActiveId}
                onManualModeChange={setManualMode}
                disabled={pending || locked}
              />
              {manualMode && !completionMode ? (
                <div className="canvas-mode-indicator" aria-live="polite">
                  手动框题
                </div>
              ) : null}
            </div>
            {detectionState.status === "error" ? (
              <StateError state={detectionState} />
            ) : null}
          </div>

          <aside className="selection-docket" aria-labelledby="selection-docket-title">
            <div className="selection-docket-header">
              <div>
                <p className="eyebrow">{supplementMode ? "本轮补选" : "本页错题"}</p>
                <h2 id="selection-docket-title">
                  {completionMode
                    ? `已保存 ${selectedRegions.length} 道`
                    : supplementMode
                      ? `本轮已选 ${selectedRegions.length} 道`
                      : `已选 ${selectedRegions.length} 道`}
                </h2>
              </div>
              <span>
                {supplementMode
                  ? `${collectionState.data.count} 道已保存 · ${regions.length} 个新框`
                  : `${displayedRegions.length} 个框${
                      detectionState.status === "success" &&
                      visibleDetectedCount < detectionState.data.candidates.length
                        ? ` · 已删 ${detectionState.data.candidates.length - visibleDetectedCount}`
                        : ""
                    }`}
              </span>
            </div>

            <ol className="selected-region-list">
              {selectedRegions.length === 0 ? (
                <li className="empty-selection">
                  {manualMode
                    ? "在原图上拖拽，框出第一道错题。"
                    : "点击原图中的 “+” 选择错题。"}
                </li>
              ) : (
                selectedRegions.map((region, index) => (
                  <li key={region.id}>
                    <button
                      type="button"
                      className={activeId === region.id ? "active" : ""}
                      onClick={() => setActiveId(region.id)}
                      disabled={locked}
                    >
                      <span className="selection-number">{index + 1}</span>
                      <span>
                        <strong>{regionSourceLabel(region)}</strong>
                        <small>
                          上 {percent(region.bbox.y)} · 高 {percent(region.bbox.height)}
                        </small>
                      </span>
                    </button>
                  </li>
                ))
              )}
            </ol>

            {activeRegion ? (
              <fieldset className="active-region-editor" disabled={pending || locked}>
                <legend>当前题目框</legend>
                {(["x", "y", "width", "height"] as const).map((field) => (
                  <label key={field}>
                    <span>{{ x: "左", y: "上", width: "宽", height: "高" }[field]}</span>
                    <input
                      aria-label={`当前框${{ x: "左", y: "上", width: "宽", height: "高" }[field]}百分比`}
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={(activeRegion.bbox[field] * 100).toFixed(1)}
                      onChange={(event) =>
                        updateActiveCoordinate(field, Number(event.currentTarget.value))
                      }
                    />
                  </label>
                ))}
              </fieldset>
            ) : null}

            <div className="selection-save-zone">
              {completionMode ? (
                <>
                  <button className="button primary save-regions-button" type="button" disabled>
                    <CheckCheck size={19} aria-hidden="true" />
                    已完成选题 {completedItems.length} 道
                  </button>
                  <button
                    className="button secondary icon-button-label save-regions-button"
                    type="button"
                    onClick={handleAddMore}
                  >
                    <Undo2 size={18} aria-hidden="true" />
                    返回框题，继续补选
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="button primary save-regions-button"
                    type="button"
                    onClick={handleSave}
                    disabled={pending || locked || selectedRegions.length === 0}
                  >
                    {batchState.status === "pending" ? (
                      <LoaderCircle className="spin" size={19} aria-hidden="true" />
                    ) : (
                      <Save size={19} aria-hidden="true" />
                    )}
                    {batchState.status === "pending"
                      ? "正在保存选题"
                      : locked
                        ? "选题已完成"
                        : `完成选题 ${selectedRegions.length} 道`}
                  </button>
                  {supplementMode ? (
                    <button
                      className="button secondary icon-button-label save-regions-button"
                      type="button"
                      onClick={handleCancelSupplement}
                    >
                      <X size={18} aria-hidden="true" />
                      取消补选
                    </button>
                  ) : null}
                </>
              )}
              {!completionMode ? (
                <p>
                  {supplementMode
                    ? `本轮只提交新框；此前 ${collectionState.data.count} 道已保存题目不会重复提交。`
                    : "只保存已选题框；完成后回到 AI 对话继续。"}
                </p>
              ) : null}
            </div>
            {batchState.status === "error" ? <StateError state={batchState} /> : null}
          </aside>
        </section>
      ) : (
        <section className="intake-empty-state">
          {assetState.status === "pending" ? (
            <LoaderCircle className="spin" size={30} aria-hidden="true" />
          ) : (
            <ScanLine size={30} aria-hidden="true" />
          )}
          <h2>
            {handoffMode
              ? assetState.status === "pending"
                ? "正在读取已上传原图"
                : "没有找到这张原图"
              : "先上传一页作业"}
          </h2>
          <p>
            {handoffMode
              ? "原图加载后即可手动框题或选择自动框题。"
              : "上传后可手动框题，也可使用自动题目框。"}
          </p>
        </section>
      )}

      {completedItems.length > 0 ? (
        <section className="selection-result" aria-labelledby="selection-result-title">
          <div className="selection-result-heading">
            <div>
              <p className="eyebrow">选题完成</p>
              <h2 id="selection-result-title">已保存 {completedItems.length} 道题</h2>
            </div>
            <span>{completedItems.length} 道裁图已保存</span>
          </div>
          <div className="selection-result-list">
            {completedItems.map((item, index) => (
              <article className="selection-result-item" key={item.problemId}>
                <span className="result-index">{index + 1}</span>
                <img src={mediaUrl(item.cropContentUrl)} alt={`第 ${index + 1} 道题的服务端裁图`} />
                <div>
                  <strong>
                    {item.selectionSource === "manual"
                      ? "手动框题"
                      : item.detectionCandidateIds.length > 1
                        ? `一道题（合并 ${item.detectionCandidateIds.length} 个识别框）`
                        : "自动题目框"}
                  </strong>
                  <code>{item.problemId}</code>
                </div>
              </article>
            ))}
          </div>
          <div className="ai-handoff-panel" aria-labelledby="ai-handoff-title">
            <div>
              <p className="eyebrow">回到 AI 对话</p>
              <h3 id="ai-handoff-title">继续处理本次教师精选</h3>
              <p>选题和裁图已经保存。</p>
            </div>
            <label htmlFor="problem-id-handoff">本次选题结果</label>
            <textarea id="problem-id-handoff" rows={4} readOnly value={handoffText} />
            <button
              className="button primary icon-button-label"
              type="button"
              onClick={() => void handleCopyHandoff()}
            >
              <Clipboard size={18} aria-hidden="true" />
              {copyState === "copied" ? "已复制，回到 AI 对话" : "复制选题结果"}
            </button>
          </div>
        </section>
      ) : null}

      {localError ? (
        <div className="error-panel" role="alert">
          <strong>请检查当前输入</strong>
          <p>{localError}</p>
        </div>
      ) : null}
      {assetState.status === "error" || collectionState.status === "error" ? (
        <StateError state={currentErrorState} />
      ) : null}
    </main>
  );
}
