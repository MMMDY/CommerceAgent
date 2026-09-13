# 数据来源与选择记录

核实日期：2026-09-12。

## 采用的来源

### 1. Bitext Retail E-commerce

- 页面：<https://huggingface.co/datasets/bitext/Bitext-retail-ecommerce-llm-chatbot-training-dataset>
- 规模：44,884 条英文 question/answer pairs，46 intents，13 categories。
- 许可：CDLA-Sharing-1.0。
- 本项目用途：只取 30 个核心 intent 的标签和少量英文 instruction；人工编写 150 条中文等价表达，并用静态 mock 补 60 条工具/槽位流程。原始长 response 不进入评测集。
- 原始 CSV SHA-256：`13a988266fed4e2b2c1ff947a89ef220ce09b5b13ac83c4a1496c0d7b81e8127`。
- 选择理由：电商垂直意图覆盖最完整、体量适中、字段简单、许可明确，最适合作为基础 intent/route 主源。

### 2. Chinese-Ambiguous-Reference

- 仓库：<https://github.com/ygan/Chinese-Ambiguous-Reference>
- 固定 commit：`3fe3a42233571914ee4a5ccaec3f3af97966d9c9`。
- 规模：1,104 条中文线上/线下购物对话（项目 README 概述为 1,000+）。
- 许可：MIT。
- 本项目用途：筛选 20 个需要补充商品属性的对话点；删除日期、地点和商家标识，截断为固定消息序列，并标注应追问的 slot。
- 源 JSON SHA-256：`36631734421c1b892b30e9f7298ab1f29bfc1de5ccc59fe14bbc91a1256377fe`。
- 选择理由：真实中文购物语境、许可明确，能补上纯英文意图集缺少的中文口语和澄清行为。

### 3. InfiniFlow Ecommerce Customer Service Workflow

- 页面：<https://huggingface.co/datasets/InfiniFlow/Ecommerce-Customer-Service-Workflow>
- 内容：3 份吹风机产品资料和 3 份用户手册；两个压缩包约 5.4 MB，解压后的 PDF 合计约 7.4 MB。
- Dataset card 许可：Apache-2.0。
- 本项目用途：只抽取 13 条规格/使用事实，形成 50 个有固定 evidence ID 的商品详情与比较 case；不复制完整 PDF。
- `product_infomation.zip` SHA-256：`4cf8edc73a6e6e5633251db7ef6855cd118428067b61fd1ff488567878b936be`。
- `user_guide.zip` SHA-256：`722d3942e663c7096b6803a7b87e060f3efedc3e5897a99712ef5037440d56ef`。
- 选择理由：下载轻、文档结构真实，适合验证最小 RAG/引用链；但 PDF 是第三方品牌手册，商用再分发前必须单独复核权利。

## 没有采用的来源

- **τ³-bench**：明确排除。其交互式任务依赖 user simulator/环境运行，超出本项目轻量静态评测范围。
- JDDC、ECD、CSDS：中文客服内容较贴合，但公开下载或再分发许可不够清晰，不进入首版 300 case。
- `dltdojo/ecommerce-faq-chatbot-dataset`：仅约 79 条且无清晰许可，不采用。
- ESCI：Apache-2.0 且适合商品检索，但完整数据约 GB 级、无中文客服对话；首版 300 case 不值得承担下载和加工成本。
- CRMArena / CRMArena-Pro：偏 CRM 且为 CC BY-NC，仅研究用途，首版不打包。

## 可复现下载

运行 `python scripts/download_eval_sources.py`。脚本使用固定 Git commit/文件路径并校验上述 SHA-256；源文件默认只保存在 `/tmp/commerce-agent-eval-sources`。
