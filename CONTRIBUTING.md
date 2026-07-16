# 贡献指南

感谢参与 `shi-homework2lark`。

## 开发原则

- 教师审核是题目进入复用流程的质量门。
- 原始数据、机器结果和人工修订必须分层保存，禁止覆盖上游证据。
- 题目资产与学生错误事件分开建模。
- 不为未来能力提前引入微服务、队列、向量数据库或学生账号系统。
- 新增外部 Provider 时，业务层只能依赖统一接口。

项目约束位于 `.trellis/spec/`。修改跨层字段或流程前，请同时检查 API、OpenAPI、前端契约、持久化映射和测试。

## 隐私门槛

提交中禁止包含：

- 真实学生姓名、学号、作业、试卷或批改痕迹；
- `.env`、API Key、Token、Base ID 或附件下载地址；
- 数据库、运行日志、OCR 原始证据和本机绝对路径；
- 未获授权的教材或试卷扫描件。

示例必须使用合成数据。发现凭据误提交时，先撤销凭据，再处理 Git 历史。

## 本地检查

```powershell
uv run --directory apps/api pytest
uv run --directory apps/api ruff check .
uv run --directory apps/api ruff format --check .
uv run --directory apps/api mypy src

npm run lint:web
npm run typecheck:web
npm run test:web
npm run build:web

python -m unittest discover -s .agents/skills/shi-homework2lark/tests -p "test_*.py"
python .agents/skills/shi-homework2lark/scripts/package_bundle.py verify --package artifacts/skills/shi-homework2lark.skill
```

涉及浏览器流程时，再运行 `npm run test:e2e`。

## Pull Request

PR 应说明：

- 改了什么、为什么改；
- 对教师流程和数据模型的影响；
- 失败时保留哪些证据、如何重试；
- 完成了哪些自动化测试；
- 是否引入第三方数据传输或新增环境变量。
