# 多页批改作业分批录入

## 为什么要分批

分批不是降低识别准确率，而是把一次过大的教师任务变成可核对、可中断、可继续的处理单元。44 人的 2 页作业有 88 页，4 页作业有 176 页；这些页面不应一次塞进同一个对话或 Provider 请求。

一个学生的完整作业是最小批次原子，不能跨批。默认每批最多 16 页：

- 每生 2 页：通常每批 8 人；
- 每生 4 页：通常每批 4 人；
- 可按设备、图片清晰度和教师核对节奏在 4～24 页内调整。

空白卷模板只保存、识别一次。后续批次只理解学生手写作答、红笔勾/叉/划线/圈和数学正误，不对每名学生重复 OCR 印刷题干。

## 准备输入

PDF/Word 先按 `source-routing.md` 渲染为逐页 JPG/JPEG/PNG。脚本允许从教师可读的任意相对或绝对路径读取，但活动目录内部只保存不可变副本和相对路径。

私有名单仍使用：

```json
{"students":[{"studentNumber":"01","name":"学生姓名"}]}
```

空白卷模板清单：

```json
{
  "pages": [
    {"pageNumber": 1, "path": "C:/private/blank-P1.png"},
    {"pageNumber": 2, "path": "C:/private/blank-P2.png"}
  ]
}
```

页码必须从 1 连续递增。

## 开始活动

```powershell
python -X utf8 <skill-root>/scripts/staged_intake.py start `
  --roster <私有名单.json> `
  --assignment-code 20260715-01 `
  --template <空白卷页面清单.json> `
  --max-pages-per-batch 16 `
  --output-dir <新的私有活动目录>
```

活动目录冻结名单快照、模板页副本、尺寸和 SHA-256。它不写飞书 Base，不调用 OCR，也不会覆盖旧活动。

## 逐批加入学生页

每一批输入完整学生页集：

```json
{
  "submissions": [
    {
      "studentNumber": "01",
      "pages": [
        {"pageNumber": 1, "path": "C:/private/01-P1.jpg"},
        {"pageNumber": 2, "path": "C:/private/01-P2.jpg"}
      ]
    }
  ]
}
```

```powershell
python -X utf8 <skill-root>/scripts/staged_intake.py add `
  --campaign-dir <活动目录> `
  --input <本批页面清单.json>
```

系统生成 `B01、B02...`。缺页、混合页数、重复学生、损坏图片或超过页数预算都会在复制前停止。不要为了塞进页数预算而拆开同一学生。

## AI/教师完成一批

先对照空白模板和批改页观察事实。结果只保存可见内容，不把 AI 推测当作学生事实：

```json
{
  "students": [
    {
      "studentNumber": "01",
      "findings": [
        {
          "pageNumber": 1,
          "questionId": "problem_xxx",
          "questionNumber": "2",
          "observedResponse": "70",
          "markEvidence": "红笔划线并打叉",
          "result": "incorrect",
          "note": ""
        }
      ]
    },
    {"studentNumber": "02", "findings": []}
  ]
}
```

- `result` 只允许 `incorrect` 或 `uncertain`；看不清时不要伪造确定错误。
- 没作答写 `observedResponse: "未作答"`。
- 全对学生也要出现，使用空 `findings`，证明该页已经处理。
- 本阶段禁止加入错误原因、错误分类、掌握状态或 Base 字段。后续才按“真实作答 → 教师/AI 归因建议 → 同题同错因分组 → 教师确认”写入 `错题记录`。

```powershell
python -X utf8 <skill-root>/scripts/staged_intake.py complete `
  --campaign-dir <活动目录> `
  --batch-id B01 `
  --input <本批观察结果.json>
```

同一份结果重复提交返回 `no_change`；不同结果不会覆盖已完成批次。`add` 与 `complete` 的活动级读改写由同一跨进程文件锁串行化，因此 Codex、Hermes 或两个终端同时处理不同批次时，不会用旧的 `campaign.json` 快照覆盖对方结果；锁等待超时会返回可重试的 `campaign_busy`。

## 查看与导出

```powershell
python -X utf8 <skill-root>/scripts/staged_intake.py status --campaign-dir <活动目录>
python -X utf8 <skill-root>/scripts/staged_intake.py export --campaign-dir <活动目录> --output <新的汇总.json>
```

标准输出只含批次、人数和页数计数。私有导出可在活动未完成时生成，但会明确 `isComplete=false`、尚未加入的人数和待处理批次；Agent 不得把部分导出描述成全班结果。

## 数据边界

- 活动目录、名单、学生页和观察结果均为教师私有数据，不提交仓库。
- 脚本不上传第三方；是否调用 AI 看图、PaddleOCR 或 Yescan 由外层对话按本次教师授权决定。
- 空白卷 `question-ocr` 每模板页最多一次；批改页不重复做整页题目 OCR。
- 该能力不自动判卷、不自动写 Base、不创建学生表、不更新掌握状态。
