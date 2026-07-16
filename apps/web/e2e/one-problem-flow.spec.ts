import { expect, test } from "@playwright/test";
import { deflateSync } from "node:zlib";

function crc32(buffer: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type: string, data: Buffer): Buffer {
  const typeBuffer = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])));
  return Buffer.concat([length, typeBuffer, data, checksum]);
}

function worksheetPng(width = 600, height = 900): Buffer {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;

  const rows: Buffer[] = [];
  for (let y = 0; y < height; y += 1) {
    const row = Buffer.alloc(1 + width * 3, 255);
    row[0] = 0;
    for (let x = 0; x < width; x += 1) {
      const isRule = y === 250 || y === 420 || (y > 280 && y < 292 && x > 80 && x < 500);
      if (isRule) {
        const offset = 1 + x * 3;
        row[offset] = 24;
        row[offset + 1] = 49;
        row[offset + 2] = 83;
      }
    }
    rows.push(row);
  }

  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", header),
    pngChunk("IDAT", deflateSync(Buffer.concat(rows))),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

test("manual-first upload skips detection and lets the teacher draw one problem", async ({ page }) => {
  let ocrRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/ocr-runs")) ocrRequests += 1;
  });
  await page.goto("/");
  await page.getByLabel("作业或试卷图片").setInputFiles({
    name: "manual-worksheet.png",
    mimeType: "image/png",
    buffer: worksheetPng(),
  });
  await page.getByRole("button", { name: "上传并手动框题" }).click();

  await expect(page.getByText("人工框题模式 · 自动框题可选")).toBeVisible();
  await expect(page.locator(".canvas-mode-indicator")).toHaveText("手动框题");
  await expect(page.getByRole("heading", { name: "已选 0 道" })).toBeVisible();

  const surface = page.getByTestId("multi-region-surface");
  await surface.scrollIntoViewIfNeeded();
  const bounds = await surface.boundingBox();
  expect(bounds).not.toBeNull();
  if (!bounds) return;
  await page.mouse.move(bounds.x + bounds.width * 0.12, bounds.y + bounds.height * 0.28);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.88, bounds.y + bounds.height * 0.46);
  await page.mouse.up();

  await expect(page.getByRole("heading", { name: "已选 1 道" })).toBeVisible();
  await page.getByRole("button", { name: "完成选题 1 道" }).click();
  await expect(page.getByRole("heading", { name: "已保存 1 道题" })).toBeVisible();
  await expect(page.getByLabel("本次选题结果")).toContainText("problem_");

  await page.getByRole("button", { name: "返回框题，继续补选" }).click();
  await expect(page.getByRole("heading", { name: "回到原图，补选漏掉的题" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "本轮已选 0 道" })).toBeVisible();
  await expect(page.getByRole("img", { name: /已保存手动题目框/ })).toBeVisible();

  await page.mouse.move(bounds.x + bounds.width * 0.12, bounds.y + bounds.height * 0.58);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.88, bounds.y + bounds.height * 0.74);
  await page.mouse.up();

  await expect(page.getByRole("heading", { name: "本轮已选 1 道" })).toBeVisible();
  await page.getByRole("button", { name: "完成选题 1 道" }).click();
  await expect(page.getByRole("heading", { name: "已保存 2 道题" })).toBeVisible();
  await expect(page.locator(".selection-result-item")).toHaveCount(2);
  await expect(page.getByRole("link")).toHaveCount(0);
  expect(ocrRequests).toBe(0);
});

test("teacher corrects split provider boxes, adds one manual box, then returns IDs to AI", async ({
  page,
}) => {
  let ocrRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes("/ocr-runs")) ocrRequests += 1;
  });
  await page.goto("/");
  await page.getByLabel("作业或试卷图片").setInputFiles({
    name: "vertical-worksheet.png",
    mimeType: "image/png",
    buffer: worksheetPng(),
  });
  await page.getByRole("button", { name: "上传并自动框题" }).click();

  await expect(page.getByText("fake · 3/3 个候选题框")).toBeVisible();
  await expect(page.getByRole("heading", { name: "已选 0 道" })).toBeVisible();

  const first = page.getByRole("button", { name: "自动题目框 1，未选择" });
  const second = page.getByRole("button", { name: "自动题目框 2，未选择" });
  await first.click();
  await second.click();
  await expect(page.getByRole("heading", { name: "已选 2 道" })).toBeVisible();
  await page.getByRole("button", { name: "合并为一题" }).click();
  await expect(page.getByRole("heading", { name: "已选 1 道" })).toBeVisible();
  await expect(page.getByText("一道题（合并 2 个识别框）")).toBeVisible();

  await page.getByRole("button", { name: "再框一题" }).click();
  const surface = page.getByTestId("multi-region-surface");
  await surface.scrollIntoViewIfNeeded();
  const bounds = await surface.boundingBox();
  expect(bounds).not.toBeNull();
  if (!bounds) return;
  await page.mouse.move(bounds.x + bounds.width * 0.12, bounds.y + bounds.height * 0.78);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width * 0.88, bounds.y + bounds.height * 0.91);
  await page.mouse.up();
  await expect(page.getByRole("heading", { name: "已选 2 道" })).toBeVisible();

  await page.getByRole("button", { name: "完成选题 2 道" }).click();
  await expect(page.getByRole("heading", { name: "已保存 2 道题" })).toBeVisible();
  await expect(page.locator(".selection-result-item")).toHaveCount(2);
  await expect(page.getByLabel("本次选题结果")).toContainText("problem_");
  await expect(page.getByRole("link")).toHaveCount(0);
  expect(ocrRequests).toBe(0);
});

test("mobile workbench keeps provider-box merge usable without page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("作业或试卷图片").setInputFiles({
    name: "mobile-worksheet.png",
    mimeType: "image/png",
    buffer: worksheetPng(),
  });
  await page.getByRole("button", { name: "上传并自动框题" }).click();

  await page.getByRole("button", { name: "自动题目框 1，未选择" }).click();
  await page.getByRole("button", { name: "自动题目框 2，未选择" }).click();
  await page.getByRole("button", { name: "合并为一题" }).click();

  await expect(page.getByRole("heading", { name: "已选 1 道" })).toBeVisible();
  await expect(page.getByText("一道题（合并 2 个识别框）")).toBeVisible();
  await expect(page.getByRole("button", { name: "完成选题 1 道" })).toBeEnabled();
  await page.getByRole("button", { name: "完成选题 1 道" }).click();
  await expect(page.getByRole("button", { name: "返回框题，继续补选" })).toBeVisible();
  await page.getByRole("button", { name: "返回框题，继续补选" }).click();
  await expect(page.getByRole("heading", { name: "本轮已选 0 道" })).toBeVisible();
  await expect(page.getByRole("button", { name: "取消补选" })).toBeVisible();
  const pageOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(pageOverflow).toBeLessThanOrEqual(1);
});
