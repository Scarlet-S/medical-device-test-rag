# Medical Device Software Testing RAG Workbench

基于 RAGFlow 构建的医疗器械控制软件测试知识库与检索增强问答工作台。

## 项目目标

本项目旨在整合医疗器械软件测试、风险管理、异常处理、权限控制和回归验证等公开资料，构建能够提供来源引用的专业知识问答系统。

## 主要功能

- 医疗器械软件测试文档知识库
- PDF 和 Word 文档解析与知识切片
- 语义检索与关键词混合检索
- 检索结果重排序
- 基于大语言模型的问答生成
- 回答来源与引用片段展示
- 自建测试问题集与效果评估

## 技术方案

- RAGFlow
- Docker
- Git / GitHub
- Embedding Model
- Rerank Model
- Large Language Model API

## 当前进度

- [x] 安装 WSL 2 与 Ubuntu
- [x] 安装并配置 Git
- [x] 初始化个人项目仓库
- [x] 安装并配置 Docker Desktop
- [x] 配置 Docker Desktop WSL 2 后端
- [x] 部署 RAGFlow v0.26.4
- [x] 验证 RAGFlow、MySQL、Elasticsearch、Redis 和 MinIO 容器
- [x] 成功访问 RAGFlow Web 工作台
- [ ] 配置聊天、Embedding 和 Rerank 模型
- [ ] 设计医疗器械软件测试资料分类体系
- [ ] 收集并整理官方公开资料
- [ ] 创建并解析领域知识库
- [ ] 配置医疗器械测试问答工作台
- [ ] 编写文档目录与元数据处理脚本
- [ ] 建立领域评估问题集
- [ ] 编写 RAGFlow API 批量评估脚本
- [ ] 编写评估指标与结果分析代码
- [ ] 完成检索参数对比实验
- [ ] 完成前端领域化定制
- [ ] 完善 GitHub 文档、截图和演示材料