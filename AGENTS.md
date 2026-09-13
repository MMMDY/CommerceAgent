# CommerceAgent 仓库执行规范

## 项目路径

- 本项目的唯一根目录为 `/home/CommerceAgent`。
- 执行文件搜索、编辑、依赖管理、数据库迁移、测试、启动、评测和 Git 操作前，必须确认当前工作目录位于 `/home/CommerceAgent`。
- 除非用户明确指定，不得在该目录之外创建本项目代码、配置、评测报告或临时交付物。

## Python 环境

- 本仓库的所有 Python 开发、依赖安装、脚本执行、测试、数据库迁移、应用启动和评测命令，都必须在名为 `commerce` 的 Conda 环境中运行。
- 执行任何项目命令前，先激活该环境：

  ```bash
  conda activate commerce
  ```

- 每次自动化命令调用都可能启动新的 Shell，不得假定之前激活的环境仍然有效。每个需要执行 Python 相关项目命令的新 Shell 会话，都必须重新激活 `commerce`。
- 如果非交互式 Shell 无法直接执行 `conda activate`，先初始化 Conda，再激活环境：

  ```bash
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate commerce
  ```

- 不得将项目依赖安装到 Conda `base`、系统 Python 或其他虚拟环境中。
- 修改依赖或执行实现验证前，必须确认 `$CONDA_DEFAULT_ENV` 的值为 `commerce`，并确认当前 `python` 来自该环境。

## Git 提交规范

- 本项目已经初始化 GitHub/Git 仓库；开始工作前先检查当前分支和工作区状态，保留用户已有的未提交变更。
- 在关键节点及时创建 Git commit，包括阶段验收完成、可独立验证的垂直切片完成、数据库 migration/协议冻结、核心安全修复以及评测基线更新。
- 每个 commit 应保持原子性，只包含同一目标的相关文件，并使用能够说明结果的提交信息。
- 提交前执行与变更风险匹配的验证；未通过验证的工作不得标记为阶段完成。若用户明确要求当前不运行测试，应如实记录未验证状态。
- 不得把无关的用户改动一起提交，不得为了提交而覆盖、回滚或删除用户已有改动。
- 未经用户明确要求，不执行 force push、历史重写或破坏性 Git 操作。

## Agent 与 Judge 模型配置

- 主 Agent 和 Rubric LLM Judge 的模型信息、API 地址及 API Key 保存在 `/home/CommerceAgent/.env`，真实调用时必须从该文件读取，不得在代码中硬编码。
- 主 Agent 使用 `.env` 中的 `MODEL`、`API_BASE`、`API_KEY`。Judge 优先使用 `JUDGE_MODEL`；未配置时按照技术设计复用 `MODEL`，并使用同一 `API_BASE` 和 `API_KEY`。
- `.env` 只允许由后端进程读取，不得发送到前端、写入 prompt、trace、日志、评测报告或 Docker 镜像。
- 不得通过 `cat`、`echo`、调试输出、异常堆栈或 Git diff 展示 `.env` 的值；检查配置时只确认变量是否存在。
- `.env` 必须保持在 `.gitignore` 中，任何真实密钥、Bearer Token 或确认 token 都不得提交到 Git。
- 除非用户明确要求，不得修改、替换或删除 `.env` 中的模型配置和密钥。
- 调用真实 Agent/Judge 前先激活 `commerce` 环境；评测报告只记录脱敏后的 provider/model 标识、配置哈希、延迟和 token 用量。

## 作用范围

本规范适用于仓库根目录及其全部子目录。若子目录存在更具体的 `AGENTS.md`，其新增约束必须与本规范兼容。
