import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { useState } from "react";

import {
  bboxFromPoints,
  isValidRegion,
  moveRegion,
  MultiRegionSelector,
  resizeRegion,
  unionNormalizedBBoxes,
} from "./MultiRegionSelector";
import type { EditableRegion } from "./MultiRegionSelector";

const initialRegions: EditableRegion[] = [
  {
    id: "candidate_1",
    detectionCandidateIds: ["candidate_1"],
    source: "detected",
    bbox: { x: 0.1, y: 0.2, width: 0.7, height: 0.2 },
    selected: false,
    readingOrder: 0,
  },
];

function Harness({ initialManualMode = false }: { initialManualMode?: boolean }) {
  const [regions, setRegions] = useState(initialRegions);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [manualMode, setManualMode] = useState(initialManualMode);
  return (
    <>
      <MultiRegionSelector
        imageUrl="http://localhost/evidence.png"
        regions={regions}
        activeId={activeId}
        manualMode={manualMode}
        onRegionsChange={setRegions}
        onActiveChange={setActiveId}
        onManualModeChange={setManualMode}
      />
      <output data-testid="region-state">{JSON.stringify(regions)}</output>
      <output data-testid="manual-state">{String(manualMode)}</output>
    </>
  );
}

describe("MultiRegionSelector", () => {
  it("normalizes, clamps moves, and resizes from a corner", () => {
    expect(bboxFromPoints({ x: 0.8, y: 0.7 }, { x: 0.2, y: 0.1 })).toEqual({
      x: 0.2,
      y: 0.1,
      width: 0.6000000000000001,
      height: 0.6,
    });
    expect(moveRegion({ x: 0.8, y: 0.8, width: 0.2, height: 0.2 }, 0.4, 0.4)).toEqual({
      x: 0.8,
      y: 0.8,
      width: 0.2,
      height: 0.2,
    });
    const resized = resizeRegion(
      { x: 0.2, y: 0.2, width: 0.4, height: 0.3 },
      "se",
      0.2,
      0.1,
    );
    expect(resized.x).toBeCloseTo(0.2);
    expect(resized.y).toBeCloseTo(0.2);
    expect(resized.width).toBeCloseTo(0.6);
    expect(resized.height).toBeCloseTo(0.4);
    expect(isValidRegion({ x: 0.1, y: 0.1, width: 0.5, height: 0.2 })).toBe(true);
    expect(isValidRegion({ x: 0.1, y: 0.1, width: 0, height: 0.2 })).toBe(false);
    expect(
      unionNormalizedBBoxes([
        { x: 0.1, y: 0.2, width: 0.4, height: 0.2 },
        { x: 0.35, y: 0.35, width: 0.5, height: 0.25 },
      ]),
    ).toEqual({ x: 0.1, y: 0.2, width: 0.75, height: 0.39999999999999997 });
  });

  it("toggles a detected candidate with pointer clicks", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "自动题目框 1，未选择" }));
    expect(screen.getByRole("button", { name: "自动题目框 1，已选择" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "自动题目框 1，已选择" }));
    expect(screen.getByRole("button", { name: "自动题目框 1，未选择" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("draws a selected manual box and exits one-shot manual mode", () => {
    render(<Harness initialManualMode />);
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

    fireEvent.pointerDown(surface, { button: 0, pointerId: 1, clientX: 60, clientY: 450 });
    fireEvent.pointerMove(surface, { pointerId: 1, clientX: 540, clientY: 630 });
    fireEvent.pointerUp(surface, { pointerId: 1, clientX: 540, clientY: 630 });

    const regions = JSON.parse(screen.getByTestId("region-state").textContent ?? "[]") as Array<{
      source: string;
      selected: boolean;
      detectionCandidateIds: string[];
      bbox: { x: number; y: number; width: number; height: number };
    }>;
    expect(regions).toHaveLength(2);
    expect(regions[1].source).toBe("manual");
    expect(regions[1].selected).toBe(true);
    expect(regions[1].detectionCandidateIds).toEqual([]);
    expect(regions[1].bbox.x).toBeCloseTo(0.1);
    expect(regions[1].bbox.y).toBeCloseTo(0.5);
    expect(regions[1].bbox.width).toBeCloseTo(0.8);
    expect(regions[1].bbox.height).toBeCloseTo(0.2);
    expect(screen.getByTestId("manual-state")).toHaveTextContent("false");
  });
});
