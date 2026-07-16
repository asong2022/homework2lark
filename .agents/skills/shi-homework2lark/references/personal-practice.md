# 学生个人精准练习

## 目标与边界

个人精准练习不是另建一套学生数据库，而是从现有 `错题记录.对应学生` 反查某名学生真正出现过的错题，再从这些原题及其可用变式中选择合适题量。飞书 Base 继续保存教师可维护的题目、错误分组和变式；姓名与学号对应关系只存在于教师私有的本地班级名单和本次练习 manifest。

当前能力既可一次生成一名学生，也可按完整名单或指定学号子集批量生成。学生账号、自动批改、自动掌握判定和批改扫描回写仍不是当前能力。

## 私有班级名单

名单使用 UTF-8 JSON：

```json
{
  "students": [
    {"studentNumber": "01", "name": "学生姓名"}
  ]
}
```

- 学号和姓名都必须唯一、非空；重复时停止，不猜测身份。
- Agent 只接受教师指定的学号，先由名单解析出唯一姓名，再以姓名查询 Base 多选字段。
- 名单不得提交到仓库，不得写入 Skill 测试夹具或普通日志。
- Base 只保存准确姓名，选项顺序按学号排列；学号不回写 Base。同名会造成姓名查询歧义，因此名单存在同名时停止生成。

## 选题规则

默认目标为 6 题，可显式设置为 1～12 题：

1. 只读取 `错题记录.对应学生` 包含该姓名的记录，并聚合到唯一来源原题。
2. 默认排除 `已掌握`；优先级为 `需再练 > 练习中 > 未开始`。
3. 同一优先级先看最近的作业/再练证据，再轮换错误分类，避免整张纸只练一种能力。
4. 第一轮每道来源原题最多选一次，保证先回到学生真正错过的题。
5. 仍有题量时，才在这些来源题的可用变式之间轮换补足；不读取异常变式，不用无关题凑数。
6. 可用题少于目标题量时，按实际数量生成并明确报告；可用题为零时停止。
7. 一道题的多个同类/不同类错误记录只形成一个来源题候选，最需要再练的状态决定其优先级。

这套规则是保守的默认值。教师可在对话中指定题量或明确要求纳入已掌握题；Agent 不根据一次正确作答自动改写掌握状态。

## 只读检查与生成

先检查真实 Base 契约：

```powershell
python <skill-root>/scripts/personal_practice.py schema-check
```

确认学生学号、练习日期和目标题量后生成本地快照：

```powershell
python <skill-root>/scripts/personal_practice.py plan `
  --roster <私有班级名单.json> `
  --student-number <学号> `
  --batch-code 20260715-01 `
  --question-count 6 `
  --output-dir session/personal/20260715-01-S001
```

输出目录必须是新目录，工具不会覆盖旧快照。其中：

- `manifest.json`：正式 Word 的不可变输入，含姓名、学号、匿名实例码和精确题目来源。
- `selection.json`：私有选题说明，记录每题来源、掌握状态、证据日期、错误分类和选择原因。
- `images/`：本次实际使用的题干图片。

再生成 Word：

```powershell
python <skill-root>/scripts/practice_sheet.py `
  --manifest session/personal/20260715-01-S001/manifest.json `
  --output session/personal/20260715-01-S001/7月15日个人练习纸.docx
```

## 按班级名单批量生成

批量命令复用同一逐生选题规则，不建立第二套“班级选题”逻辑：

```powershell
python <skill-root>/scripts/class_practice.py schema-check
python <skill-root>/scripts/class_practice.py build `
  --roster <私有班级名单.json> `
  --batch-code 20260715-01 `
  --question-count 6 `
  --output-dir <新的班级批次目录>
```

默认遍历整份名单。只生成部分学生时可重复传入 `--student-number <学号>`；`Sxxx` 仍由完整名单顺序决定。例如只生成名单中的 03 号，仍使用 `S003`。

批次目录包含：

- `batch-summary.json`：私有批次摘要；
- `班级个人练习清单.csv`：带 UTF-8 BOM 的教师清单；
- `students/Sxxx/manifest.json` 与 `selection.json`；
- `students/Sxxx/Sxxx-个人练习纸.docx`。

文件名不含真实姓名或学号，Word 正文才填写身份。没有合格错题的学生在清单标记 `no_eligible_items`，不生成空白 Word。批量命令在同一次运行复用 Base schema、变式目录、题目与附件缓存；任一技术错误会删除新批次临时目录，不覆盖旧批次。

## 个人 Manifest

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
      "source": {
        "type": "original",
        "questionId": "problem_xxx"
      }
    }
  ]
}
```

- 标题从批次日期派生为 `M月D日个人练习纸`。
- 第一页自动填写姓名和学号。
- 题目按顺序连续流入 Word，不按估算容量提前分页；只有当前页真正放不下下一道完整题目块时才自然换页。
- 重复页眉右上角使用 `YYYYMMDD-NN-Sxxx-P` 加 Word `PAGE` 字段，如第一页显示 `20260715-01-S001-P1`。
- `Sxxx` 只表示该次私有名单中的顺序，不含姓名、学号、Base token 或远端记录 ID；本地 manifest 才保存对应关系。
- 题号仍由 `R01...` 精确映射到原题或变式，题干图片与来源规则沿用正式练习纸模板。

## 失败与隐私

- 名单不存在、身份不唯一、Base 结构不符、附件不可读、输出目录已存在时停止并给出明确错误。
- 单条 Base 记录不完整时跳过并在私有 `selection.json` 计数；绝不把不完整题目塞入学生卷。
- 标准输出只报告题数、版式模式和文件名，不猜测 Word 实际页数，也不打印姓名、学号、完整题干或附件 URL。
- 生成 Word、打印或发送仍是教师可见动作；个人 manifest、名单和练习纸应按学生数据管理，不上传到无关第三方。
- 班级批量标准输出同样只报告计数；真实姓名、学号、题干和本地路径只出现在私有产物中。
