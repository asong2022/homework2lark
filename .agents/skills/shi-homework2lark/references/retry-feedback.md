# 再练回收自动定位与反馈

## 输入边界

AI/Hermes 或 `shi-ocr` 负责从教师批改后的图片/PDF观察：

- 右上角页面文字码；
- 页面上可见题号；
- 学生真实作答；
- 红笔勾、叉、划线、圈及教师批注；
- `correct / partial / incorrect / uncertain / not_observed` 结果。

`retry_batch.py` 不自行看图。它只把观察结果可靠映射到不可变练习 manifest，禁止把“有红笔”直接解释成“答错”。

## 准备回收计划

观察输入：

```json
{
  "observedAt": "2026-07-15T20:00:00+08:00",
  "pages": [
    {
      "pageCode": "20260715-01-S001-P1",
      "items": [
        {
          "itemNumber": 2,
          "observedResponse": "把135°判断成锐角",
          "markEvidence": "红笔打叉并圈出135°",
          "result": "incorrect",
          "teacherJudgment": "可选：缺少直角参照"
        }
      ]
    }
  ]
}
```

```powershell
python -X utf8 <skill-root>/scripts/retry_batch.py prepare `
  --manifest <单份manifest.json或整班批次目录> `
  --input <AI/OCR观察.json> `
  --output <新的私有反馈计划.json>
```

定位链：

```text
pageCode → batchCode / Sxxx / 实际页
可见题号 → Rxx
manifest Rxx → questionId / optional variantId
```

Word 自然分页时，manifest 不预估哪道题在第几页；因此页面码验证批次和实例，可见题号负责 `Rxx` 定位。错误页面码、题号越界、同一题重复出现或稳定来源冲突全部拒绝。

## 掌握投影规则

- `incorrect / partial` → 默认 `需再练`；
- `correct` → 默认 `练习中`，一次正确不能自动宣称 `已掌握`；
- `uncertain / not_observed` → 不自动修改掌握状态，进入单一人工异常清单；
- 只有教师明确给出 `teacherMastery`，且标记 `已掌握` 时同时给出教师判断，才能覆盖默认建议。

真实作答、批改痕迹、结果、教师判断和掌握投影分别保存，不互相代替。

## 提交与 Base 投影

先验证计划，再追加本地事件：

```powershell
python -X utf8 <skill-root>/scripts/retry_batch.py validate --plan <反馈计划.json>
python -X utf8 <skill-root>/scripts/retry_batch.py commit `
  --plan <反馈计划.json> `
  --event-store <私有再练事件.jsonl>
```

事件 ID 由批次、匿名实例、`Rxx`、原题/变式来源、观察事实和时间稳定生成。相同计划重跑不会重复追加。

`validate` 会从不可变 `events` 重新计算全部 `baseProjections` 和人工处理计数；两者只要被单独修改、错位或遗漏，整个计划就会被拒绝。Base 当前状态只接受时间严格晚于 `最近再练时间` 的投影。补录的旧事件仍追加到本地历史，但不会把较新的掌握状态和时间覆盖回去。

`commit` 后读取计划中的 `baseProjections`，使用 `lark-base` 在既有授权范围内更新当前投影并回读：

- 实名个人练习：按 `questionId + studentName` 定位其相关 `错题记录`，更新组级 `再练反馈/掌握状态/最近再练时间`；
- 匿名练习：只更新原题的 `掌握状态/最近再练时间`，完整摘要保留在本地事件；教师明确指定错误组时可更新组级反馈；
- 不确定或无法唯一定位：不写 Base；
- Base 失败：本地事件保留，用同一事件 ID 只重试投影。

Base 是教师工作台当前状态，本地 JSONL 是不可覆盖的逐次历史。不得用反馈改写原题、原始典型错例或底层本地批改证据。
