"use client";

/* eslint-disable @next/next/no-img-element -- The selectable evidence image needs native pointer geometry. */

import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { useRef } from "react";

import type { NormalizedBBox } from "@/lib/contracts";

type Point = { x: number; y: number };

type ImageRegionSelectorProps = {
  imageUrl: string;
  value: NormalizedBBox | null;
  onChange: (bbox: NormalizedBBox) => void;
  disabled?: boolean;
};

const MIN_NORMALIZED_SIZE = 0.005;

function clamp(value: number): number {
  return Math.min(1, Math.max(0, value));
}

function pointFromEvent(event: ReactPointerEvent<HTMLDivElement>): Point {
  const rect = event.currentTarget.getBoundingClientRect();
  return {
    x: clamp((event.clientX - rect.left) / Math.max(rect.width, 1)),
    y: clamp((event.clientY - rect.top) / Math.max(rect.height, 1)),
  };
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

export function isValidSelection(value: NormalizedBBox | null): value is NormalizedBBox {
  return (
    value !== null &&
    value.width >= MIN_NORMALIZED_SIZE &&
    value.height >= MIN_NORMALIZED_SIZE &&
    value.x + value.width <= 1 &&
    value.y + value.height <= 1
  );
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export function ImageRegionSelector({
  imageUrl,
  value,
  onChange,
  disabled = false,
}: ImageRegionSelectorProps) {
  const dragStart = useRef<Point | null>(null);

  const updateNumber = (field: keyof NormalizedBBox, percentage: number) => {
    if (!Number.isFinite(percentage)) return;
    const next: NormalizedBBox = value ?? { x: 0, y: 0, width: 0.5, height: 0.5 };
    const normalized = clamp(percentage / 100);
    const updated = { ...next, [field]: normalized };
    if (field === "x" && updated.x + updated.width > 1) {
      updated.width = 1 - updated.x;
    }
    if (field === "y" && updated.y + updated.height > 1) {
      updated.height = 1 - updated.y;
    }
    if (field === "width") {
      updated.width = Math.min(updated.width, 1 - updated.x);
    }
    if (field === "height") {
      updated.height = Math.min(updated.height, 1 - updated.y);
    }
    onChange(updated);
  };

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    const start = pointFromEvent(event);
    dragStart.current = start;
    onChange({ x: start.x, y: start.y, width: 0, height: 0 });
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || dragStart.current === null) return;
    onChange(bboxFromPoints(dragStart.current, pointFromEvent(event)));
  };

  const finishPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragStart.current !== null) {
      onChange(bboxFromPoints(dragStart.current, pointFromEvent(event)));
    }
    dragStart.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const overlayStyle: CSSProperties | undefined = value
    ? {
        left: percent(value.x),
        top: percent(value.y),
        width: percent(value.width),
        height: percent(value.height),
      }
    : undefined;

  return (
    <div className="selection-block">
      <div
        className="selection-surface"
        data-testid="selection-surface"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishPointer}
        onPointerCancel={finishPointer}
        aria-label="在原图上拖动框选一道题"
        role="group"
        tabIndex={disabled ? -1 : 0}
      >
        <img
          src={imageUrl}
          alt="已上传的原始作业图片，请在图中框选一道题"
          draggable={false}
        />
        {overlayStyle ? (
          <span className="selection-overlay" style={overlayStyle} aria-hidden="true" />
        ) : null}
      </div>

      <fieldset className="bbox-fields" disabled={disabled}>
        <legend>框选区域（占原图百分比）</legend>
        {(["x", "y", "width", "height"] as const).map((field) => (
          <label key={field}>
            <span>{{ x: "左", y: "上", width: "宽", height: "高" }[field]}</span>
            <input
              aria-label={`区域${{ x: "左", y: "上", width: "宽", height: "高" }[field]}百分比`}
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={((value?.[field] ?? 0) * 100).toFixed(1)}
              onChange={(event) => updateNumber(field, Number(event.currentTarget.value))}
            />
          </label>
        ))}
      </fieldset>

      <p className={isValidSelection(value) ? "selection-summary" : "selection-summary invalid"}>
        {value
          ? `左 ${percent(value.x)} · 上 ${percent(value.y)} · 宽 ${percent(value.width)} · 高 ${percent(value.height)}`
          : "请在图片上按住并拖动，框选一道完整题目。"}
      </p>
    </div>
  );
}
