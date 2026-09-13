# 数据许可说明

本目录是多来源评测数据集合，不能用一个笼统的软件许可证覆盖所有记录。每条 `cases.jsonl` 记录的 `source.license` 字段标明适用来源。

1. Bitext 派生记录：上游为 **CDLA-Sharing-1.0**。使用、修改和再分发时须保留来源署名，并按该许可证的 Sharing 条款处理增强数据。许可证原文：<https://cdla.dev/sharing-1-0/>。
2. Chinese-Ambiguous-Reference 派生记录：上游为 **MIT License**，需保留其版权和许可声明。仓库：<https://github.com/ygan/Chinese-Ambiguous-Reference>。
3. InfiniFlow 数据集卡标注 **Apache-2.0**。本项目只保存从资料中抽取的最小事实，不附带原 PDF。由于原文件是 Philips 品牌手册，数据集卡许可是否覆盖其中全部第三方内容并不确定；当前仅建议内部研究/原型评测，正式商用或公开再分发前应完成单独版权复核。
4. `CommerceAgent synthetic safety fixtures` 为本项目人工编写内容，按项目自身数据许可处理。

本说明不是法律意见。下载的完整上游文件不提交到项目仓库；可通过 `scripts/download_eval_sources.py` 从原发布方重新获取。
