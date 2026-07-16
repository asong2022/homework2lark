# 正式练习纸模板

## 目标

正式练习纸服务于打印、学生作答和后续 AI/OCR 回收，不是展示型海报。版式优先保证：题目完整、作答空间可用、页面身份稳定、Word 可继续人工修改。

## Manifest

新生成的普通组卷使用 `practice-sheet-v2`：

```json
{
  "batchCode": "20260715-01",
  "manifestVersion": "practice-sheet-v2",
  "items": [
    {
      "itemCode": "R01",
      "question": "在括号里填上合适的单位。",
      "answerLines": 0,
      "source": {
        "type": "original",
        "questionId": "problem_xxx"
      }
    },
    {
      "itemCode": "R02",
      "question": "在数轴下面的方框里填上合适的小数。",
      "stemImage": {
        "path": "images/number-line.png",
        "description": "0 到 2 的数轴和三个待填写方框"
      },
      "answerLines": 1,
      "source": {
        "type": "variant",
        "questionId": "problem_xxx",
        "variantId": "variant:v1:xxx"
      }
    }
  ]
}
```

- 普通组卷顶层字段固定为 `batchCode / manifestVersion / items`。标题日期和页面识别码均从批次码及 Word 实际页码派生，不重复保存日期、标题或页面码。
- `batchCode` 使用有效日历日期与当日序号 `YYYYMMDD-NN`；标题为 `M月D日练习纸`，实际页面码为 `batchCode-P{Word PAGE}`。
- `items` 是顺序题目清单。生成器不预估页容量、不插入人工分页符，由 Word 在实际放不下下一道完整题目块时自然换页；整个 Word 仍只有一个 A4 分节。
- `itemCode` 在整份练习中从 `R01` 连续排列。它是 manifest 稳定代码；学生卷显示相同顺序的简洁数字题号 `1.、2.……`。
- `source.type` 只能是 `original` 或 `variant`；两者都需要 `questionId`，变式还必须包含 `variantId`。
- `answerLines` 为 `0..8`。填空、选择等题可为 0；计算、解决问题和解释题按真实作答需要预留。
- `stemImage` 可省略。存在时必须包含可读的 JPG/JPEG/PNG 路径和非空说明；相对路径以 manifest 所在目录为基准，绝对路径也允许。

个人精准练习使用 `personal-practice-v2`，并在顶层增加唯一的 `student`：

```json
{
  "batchCode": "20260715-01",
  "manifestVersion": "personal-practice-v2",
  "student": {
    "name": "学生姓名",
    "studentNumber": "01",
    "instanceCode": "S001"
  },
  "items": [
    {
      "itemCode": "R01",
      "question": "完整题干文本",
      "answerLines": 2,
      "source": {"type": "original", "questionId": "problem_xxx"}
    }
  ]
}
```

- 个人标题派生为 `M月D日个人练习纸`，第一页姓名、学号由 manifest 自动填写。
- `instanceCode` 必须是 `S001...S999`，只表示私有名单中的顺序；可见页码为 `batchCode-instanceCode-P{Word PAGE}`。
- 可见页码不含姓名、学号、Base token 或远端记录 ID；隐私身份映射只留在本地 manifest。
- 普通 manifest 禁止出现 `student`；个人 manifest 必须且只能出现上述三个学生字段。

## 固定版式

- A4 纵向；左右页边距 16 mm，上下页边距 13 mm。
- 第一页标题为黑体 16 磅、加粗、居中；标题下方为宋体 12 磅的姓名与学号区。普通组卷保留填写横线，个人练习自动填入姓名和学号；后续页不重复大标题。
- 正文使用宋体 12 磅、黑色。题号加粗，题干保持自然左对齐；不使用装饰色、横幅或大面积表格包装正文。
- 重复页眉中放置一个无底色、无边框文本框。普通页码使用 42 mm × 8 mm；较长的个人页码使用 48 mm × 8 mm，并保持相同右边界。文本框相对页面定位，静态批次前缀后连接 Word `PAGE` 字段，因此每一张实际页面都显示完整识别码，例如 `20260715-01-P1` 或 `20260715-01-S001-P1`；不锚定正文位置，不在页脚重复。
- 页脚只显示居中的 Word `PAGE` 页码字段。

## 题目块

一题只使用一个连续排版块：

```text
数字题号 + 题干文本
可选题干图片
可选作答横线
```

- 题干图片必须位于本题文本下方，单独成段并左对齐；无图题不创建空白图片框。
- 图片保持原比例，最大 145 mm × 65 mm。输入应是已经清理过的题内视觉，不得夹带相邻题目、学生作答或批改痕迹。
- 题干、题图和作答空间设置 keep-with-next/keep-together。生成器按 `items` 连续排版；如果当前页剩余空间放不下整题，Word 将完整题目块移到下一页。
- manifest 冻结题目顺序与来源，不预先声明物理页。实际分页只属于 Word 版式结果，不反写成新的题目来源。
- `practice-sheet-v1` / `personal-practice-v1` 仅为旧样稿兼容读取，仍保留当时的显式页与硬分页语义；所有新组题必须写 v2。

## 质量门

生成后必须使用 Word 或文档 Skill 渲染全部页面并逐页检查：

- 标题确为 16 磅黑体，日期与批次码一致；
- 个人练习的姓名、学号与私有名单一致，可见页码不泄露二者；
- 每页右上角识别码完整、无遮挡、位置稳定；
- 只有一个分节，v2 正文不含人工硬分页符；只有内容真正放不下时才由 Word 自动产生下一页；
- 题图在对应文本下方、左对齐、无拉伸、无残缺相邻内容；
- 同一道题未跨页，页尾没有孤立题干；
- 作答空间与题型相称，没有无教学用途的大面积空白页。
