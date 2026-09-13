# CommerceAgent 仓库执行规范

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

## 作用范围

本规范适用于仓库根目录及其全部子目录。若子目录存在更具体的 `AGENTS.md`，其新增约束必须与本规范兼容。
