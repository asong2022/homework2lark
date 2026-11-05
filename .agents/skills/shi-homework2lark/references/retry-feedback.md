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
- `uncertain / not_observed` → 保留未确定事实，不修改状态，也不算答错；只对无法继续定位的具体问题询问教师；
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

新计划版本为 `retry-feedback-plan-v2`；`validate` 会从不可变 `events` 重算投影和异常计数，拒绝被单独篡改的投影，并能校验旧 v1 计划后转换到安全的 v2 语义。事件 ID 与事件格式不变，旧历史不必重写。

`commit` 只追加本地事件，不自动写 Base。投影有明确作用域：

- 实名个人练习：`targetScope=student_private`、`canUpdateBase=false`。该生结果只进入私有历史和个人下次选题，不能直接覆盖包含其他学生的组级状态；
- 匿名练习：只有可观察结果的题目级投影可作为 Agent 的写入建议，仍须遵守原有授权和时间顺序；教师明确提供整组反馈后才可更新相应组级状态；
- 不确定或无法唯一定位：不写 Base；
- Base 失败：本地事件保留，用同一事件 ID 只重试投影。

Base 是教师工作台当前状态，本地 JSONL 是不可覆盖的逐次历史。不得用反馈改写原题、原始典型错例或底层本地批改证据。

## 下次选题、变式和统计

个人/整班组题传入同一个本班 `--event-store`，即可消费已提交的真实反馈。生成变式前可先提取私有事实卡：

```powershell
python -X utf8 <skill-root>/scripts/retry_evidence.py context `
  --event-store <本班私有再练事件.jsonl> --question-id <系统题目ID> `
  --roster <私有班级名单.json> --student-number <学号> --output <新上下文.json>
python -X utf8 <skill-root>/scripts/retry_evidence.py summary `
  --event-store <本班私有再练事件.jsonl> --selection <selection.json或班级批次目录> `
  --output <新统计.json>
```

`context` 保留最近观察及最近可观察结果，原题、学生真实作答、教师判断和 AI 推断分别呈现。`summary` 以一次作答事件为单位，正确率分母仅包括 `correct/partial/incorrect`；`uncertain/not_observed` 单独计数。多次练习不是多名学生。按错误分类的统计表示本次练习的目标分类，不冒充新一次错误诊断；一题针对多个原因时分类小计不能相加为总人数。没有身份的事件只参加匿名统计，不进入个人状态。
