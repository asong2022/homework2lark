"use client";

/* eslint-disable @next/next/no-img-element -- Native image geometry is required for pointer overlays. */

import { Check, Plus } from "lucide-react";
import type {
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { useMemo, useState } from "react";

import type { NormalizedBBox, RegionSelectionSource } from "@/lib/contracts";

type Point = { x: number; y: number };
type Corner = "nw" | "ne" | "sw" | "se";

export type EditableRegion = {
  id: string;
  detectionCandidateIds: string[];
  source: RegionSelectionSource;
  bbox: NormalizedBBox;
  selected: boolean;
  readingOrder: number;
};

type Interaction =
  | {
      mode: "draw";
      pointerId: number;
      start: Point;
    }
  | {
      mode: "move";
      pointerId: number;
      regionId: string;
      start: Point;
      startBBox: NormalizedBBox;
      wasSelected: boolean;
    }
  | {
      mode: "resize";
      pointerId: number;
      regionId: string;
      start: Point;
      startBBox: NormalizedBBox;
      corner: Corner;
    };

type MultiRegionSelectorProps = {
  imageUrl: string;
  regions: EditableRegion[];
  activeId: string | null;
  manualMode: boolean;
  readOnlyRegionIds?: ReadonlySet<string>;
  onRegionsChange: (regions: EditableRegion[]) => void;
  onActiveChange: (regionId: string | null) => void;
  onManualModeChange: (enabled: boolean) => void;
  disabled?: boolean;
};

export const MIN_NORMALIZED_REGION_SIZE = 0.008;

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value));
}

export function bboxFromPoints(start: Point, end: Point): NormalizedBBox {
  const x = Math.min(start.x, end.x);
  const y = Math.min(start.y, end.y);
  return {
    x,
    y,
    width: Math.max(start.x, end.x) - x,
    height: Math.max(start.y, end.y) - y,
  };
}

export function isValidRegion(bbox: NormalizedBBox | null): bbox is NormalizedBBox {
  return (
    bbox !== null &&
    Number.isFinite(bbox.x) &&
    Number.isFinite(bbox.y) &&
    Number.isFinite(bbox.width) &&
    Number.isFinite(bbox.height) &&
    bbox.x >= 0 &&
    bbox.y >= 0 &&
    bbox.width >= MIN_NORMALIZED_REGION_SIZE &&
    bbox.height >= MIN_NORMALIZED_REGION_SIZE &&
    bbox.x + bbox.width <= 1.000001 &&
    bbox.y + bbox.height <= 1.000001
  );
}

export function unionNormalizedBBoxes(bboxes: NormalizedBBox[]): NormalizedBBox {
  if (bboxes.length === 0) {
    throw new Error("At least one bounding box is required");
  }
  const left = Math.min(...bboxes.map((bbox) => bbox.x));
  const top = Math.min(...bboxes.map((bbox) => bbox.y));
  const right = Math.max(...bboxes.map((bbox) => bbox.x + bbox.width));
  const bottom = Math.max(...bboxes.map((bbox) => bbox.y + bbox.height));
  return {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
  };
}

export function moveRegion(
  bbox: NormalizedBBox,
  deltaX: number,
  deltaY: number,
): NormalizedBBox {
  return {
    ...bbox,
    x: clamp(bbox.x + deltaX, 0, 1 - bbox.width),
    y: clamp(bbox.y + deltaY, 0, 1 - bbox.height),
  };
}

export function resizeRegion(
  bbox: NormalizedBBox,
  corner: Corner,
  deltaX: number,
  deltaY: number,
): NormalizedBBox {
  const originalRight = bbox.x + bbox.width;
  const originalBottom = bbox.y + bbox.height;
  let left = bbox.x;
  let top = bbox.y;
  let right = originalRight;
  let bottom = originalBottom;

  if (corner.includes("w")) {
    left = clamp(bbox.x + deltaX, 0, originalRight - MIN_NORMALIZED_REGION_SIZE);
  } else {
    right = clamp(originalRight + deltaX, bbox.x + MIN_NORMALIZED_REGION_SIZE, 1);
  }
  if (corner.includes("n")) {
    top = clamp(bbox.y + deltaY, 0, originalBottom - MIN_NORMALIZED_REGION_SIZE);
  } else {
    bottom = clamp(originalBottom + deltaY, bbox.y + MIN_NORMALIZED_REGION_SIZE, 1);
  }
  return { x: left, y: top, width: right - left, height: bottom - top };
}

function percent(value: number): string {
  return `${value * 100}%`;
}

function overlayStyle(bbox: NormalizedBBox): CSSProperties {
  return {
    left: percent(bbox.x),
    top: percent(bbox.y),
    width: percent(bbox.width),
    height: percent(bbox.height),
  };
}

export function MultiRegionSelector({
  imageUrl,
  regions,
  activeId,
  manualMode,
  readOnlyRegionIds,
  onRegionsChange,
  onActiveChange,
  onManualModeChange,
  disabled = false,
}: MultiRegionSelectorProps) {
  const [interaction, setInteraction] = useState<Interaction | null>(null);
  const [draftBBox, setDraftBBox] = useState<NormalizedBBox | null>(null);

  const selectedNumbers = useMemo(() => {
    const ordered = [...regions]
      .filter((region) => region.selected)
      .sort((left, right) =>
        left.bbox.y === right.bbox.y
          ? left.bbox.x - right.bbox.x
          : left.bbox.y - right.bbox.y,
      );
    return new Map(ordered.map((region, index) => [region.id, index + 1]));
  }, [regions]);

  const pointFromClient = (clientX: number, clientY: number, element: HTMLElement): Point => {
    const surface = element.closest<HTMLElement>(".multi-region-surface");
    const rect = surface?.getBoundingClientRect();
    if (!rect) return { x: 0, y: 0 };
    return {
      x: clamp((clientX - rect.left) / Math.max(rect.width, 1)),
      y: clamp((clientY - rect.top) / Math.max(rect.height, 1)),
    };
  };

  const replaceRegion = (regionId: string, bbox: NormalizedBBox) => {
    onRegionsChange(
      regions.map((region) => (region.id === regionId ? { ...region, bbox } : region)),
    );
  };

  const beginDraw = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || !manualMode || event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const start = pointFromClient(event.clientX, event.clientY, event.currentTarget);
    setInteraction({ mode: "draw", pointerId: event.pointerId, start });
    setDraftBBox({ x: start.x, y: start.y, width: 0, height: 0 });
    onActiveChange(null);
  };

  const moveDraw = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || interaction?.mode !== "draw") return;
    setDraftBBox(
      bboxFromPoints(
        interaction.start,
        pointFromClient(event.clientX, event.clientY, event.currentTarget),
      ),
    );
  };

  const finishDraw = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (interaction?.mode !== "draw") return;
    const bbox = bboxFromPoints(
      interaction.start,
      pointFromClient(event.clientX, event.clientY, event.currentTarget),
    );
    setInteraction(null);
    setDraftBBox(null);
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (!isValidRegion(bbox)) return;
    const id = `manual-${globalThis.crypto.randomUUID()}`;
    const nextReadingOrder =
      regions.reduce((maximum, region) => Math.max(maximum, region.readingOrder), -1) + 1;
    onRegionsChange([
      ...regions,
      {
        id,
        detectionCandidateIds: [],
        source: "manual",
        bbox,
        selected: true,
        readingOrder: nextReadingOrder,
      },
    ]);
    onActiveChange(id);
    onManualModeChange(false);
  };

  const beginMove = (event: ReactPointerEvent<HTMLDivElement>, region: EditableRegion) => {
    if (disabled || manualMode || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setInteraction({
      mode: "move",
      pointerId: event.pointerId,
      regionId: region.id,
      start: pointFromClient(event.clientX, event.clientY, event.currentTarget),
      startBBox: region.bbox,
      wasSelected: region.selected,
    });
    onActiveChange(region.id);
    if (!region.selected) {
      onRegionsChange(
        regions.map((item) => (item.id === region.id ? { ...item, selected: true } : item)),
      );
    }
  };

  const beginResize = (
    event: ReactPointerEvent<HTMLButtonElement>,
    region: EditableRegion,
    corner: Corner,
  ) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setInteraction({
      mode: "resize",
      pointerId: event.pointerId,
      regionId: region.id,
      start: pointFromClient(event.clientX, event.clientY, event.currentTarget),
      startBBox: region.bbox,
      corner,
    });
    onActiveChange(region.id);
    if (!region.selected) {
      onRegionsChange(
        regions.map((item) => (item.id === region.id ? { ...item, selected: true } : item)),
      );
    }
  };

  const moveEdit = (
    event: ReactPointerEvent<HTMLDivElement> | ReactPointerEvent<HTMLButtonElement>,
  ) => {
    if (disabled || !interaction || interaction.mode === "draw") return;
    event.preventDefault();
    event.stopPropagation();
    const point = pointFromClient(event.clientX, event.clientY, event.currentTarget);
    const deltaX = point.x - interaction.start.x;
    const deltaY = point.y - interaction.start.y;
    if (interaction.mode === "move") {
      replaceRegion(interaction.regionId, moveRegion(interaction.startBBox, deltaX, deltaY));
      return;
    }
    replaceRegion(
      interaction.regionId,
      resizeRegion(interaction.startBBox, interaction.corner, deltaX, deltaY),
    );
  };

  const finishEdit = (
    event: ReactPointerEvent<HTMLDivElement> | ReactPointerEvent<HTMLButtonElement>,
    cancelled = false,
  ) => {
    if (!interaction || interaction.mode === "draw") return;
    const end = pointFromClient(event.clientX, event.clientY, event.currentTarget);
    const moved =
      Math.abs(end.x - interaction.start.x) + Math.abs(end.y - interaction.start.y) > 0.002;
    setInteraction(null);
    event.preventDefault();
    event.stopPropagation();
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (
      !cancelled &&
      interaction.mode === "move" &&
      !moved &&
      interaction.wasSelected
    ) {
      onRegionsChange(
        regions.map((region) =>
          region.id === interaction.regionId ? { ...region, selected: false } : region,
        ),
      );
    }
  };

  const handleRegionKeyDown = (
    event: ReactKeyboardEvent<HTMLDivElement>,
    region: EditableRegion,
  ) => {
    if (disabled) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onActiveChange(region.id);
      onRegionsChange(
        regions.map((item) =>
          item.id === region.id ? { ...item, selected: !item.selected } : item,
        ),
      );
    }
    if ((event.key === "Delete" || event.key === "Backspace") && activeId === region.id) {
      event.preventDefault();
      onRegionsChange(regions.filter((item) => item.id !== region.id));
      onActiveChange(null);
    }
  };

  return (
    <div className="multi-region-block">
      <div
        className={`multi-region-surface${manualMode ? " manual-mode" : ""}`}
        data-testid="multi-region-surface"
        onPointerDown={beginDraw}
        onPointerMove={moveDraw}
        onPointerUp={finishDraw}
        onPointerCancel={finishDraw}
        role="group"
        aria-label="作业原图与题目候选框"
      >
        <img src={imageUrl} alt="已上传的作业原图，叠加可选择的题目框" draggable={false} />
        {regions.map((region) => {
          const selectionNumber = selectedNumbers.get(region.id);
          const readOnly = readOnlyRegionIds?.has(region.id) ?? false;
          const active = !readOnly && activeId === region.id;
          const sourceLabel =
            region.source === "manual"
              ? "手动"
              : region.detectionCandidateIds.length > 1
                ? `合并（${region.detectionCandidateIds.length} 个来源框）`
                : "自动";
          const accessibleLabel = readOnly
            ? `已保存${sourceLabel}题目框 ${region.readingOrder + 1}`
            : `${sourceLabel}题目框 ${region.readingOrder + 1}，${
                region.selected ? "已选择" : "未选择"
              }`;
          return (
            <div
              key={region.id}
              className={[
                "region-box",
                region.source === "manual" ? "manual" : "detected",
                region.selected ? "selected" : "",
                active ? "active" : "",
                readOnly ? "saved" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              style={overlayStyle(region.bbox)}
              role={readOnly ? "img" : "button"}
              tabIndex={disabled || readOnly ? -1 : 0}
              aria-pressed={readOnly ? undefined : region.selected}
              aria-label={accessibleLabel}
              onPointerDown={(event) => {
                if (readOnly) {
                  event.preventDefault();
                  event.stopPropagation();
                  return;
                }
                beginMove(event, region);
              }}
              onPointerMove={readOnly ? undefined : moveEdit}
              onPointerUp={readOnly ? undefined : (event) => finishEdit(event)}
              onPointerCancel={
                readOnly ? undefined : (event) => finishEdit(event, true)
              }
              onKeyDown={
                readOnly ? undefined : (event) => handleRegionKeyDown(event, region)
              }
            >
              <span className="region-choice" aria-hidden="true">
                {selectionNumber ? (
                  <>
                    <Check size={13} strokeWidth={3} />
                    <span>{selectionNumber}</span>
                  </>
                ) : (
                  <Plus size={16} strokeWidth={3} />
                )}
              </span>
              {active && !disabled ?
                (["nw", "ne", "sw", "se"] as const).map((corner) => (
                  <button
                    key={corner}
                    className={`region-handle handle-${corner}`}
                    type="button"
                    aria-label={`缩放当前题目框${corner}`}
                    onPointerDown={(event) => beginResize(event, region, corner)}
                    onPointerMove={moveEdit}
                    onPointerUp={(event) => finishEdit(event)}
                    onPointerCancel={(event) => finishEdit(event, true)}
                  />
                )) : null}
            </div>
          );
        })}
        {draftBBox ? (
          <span className="region-box manual draft" style={overlayStyle(draftBBox)} />
        ) : null}
      </div>
    </div>
  );
}
