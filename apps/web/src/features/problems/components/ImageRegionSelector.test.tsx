import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  bboxFromPoints,
  ImageRegionSelector,
  isValidSelection,
} from "./ImageRegionSelector";

describe("ImageRegionSelector", () => {
  it("normalizes a reverse drag into a top-left bbox", () => {
    expect(bboxFromPoints({ x: 0.8, y: 0.7 }, { x: 0.2, y: 0.1 })).toEqual({
      x: 0.2,
      y: 0.1,
      width: 0.6000000000000001,
      height: 0.6,
    });
  });

  it("rejects zero-size and out-of-range selections", () => {
    expect(isValidSelection({ x: 0, y: 0, width: 0, height: 0.5 })).toBe(false);
    expect(isValidSelection({ x: 0.8, y: 0, width: 0.3, height: 0.5 })).toBe(false);
    expect(isValidSelection({ x: 0.1, y: 0.1, width: 0.4, height: 0.3 })).toBe(true);
  });

  it("allows precise coordinate correction with number fields", () => {
    const onChange = vi.fn();
    render(
      <ImageRegionSelector
        imageUrl="http://localhost/evidence.png"
        value={{ x: 0.1, y: 0.2, width: 0.5, height: 0.4 }}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByLabelText("区域左百分比"), { target: { value: "25" } });
    expect(onChange).toHaveBeenLastCalledWith({ x: 0.25, y: 0.2, width: 0.5, height: 0.4 });
  });
});
