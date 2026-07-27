# RAGFlow 本地部署与项目运行说明

本文记录医疗器械软件测试知识库在 Windows 11、WSL 2 和 Docker Desktop 环境中的部署与验证方法。

> 本文中的路径均为示例，不包含个人本地目录。API Key、密码和真实 `.env` 文件不得提交到Git仓库。

## 1. 已验证环境

| 组件 | 已验证版本或配置 |
|---|---|
| 操作系统 | Windows 11 64-bit |
| Linux环境 | WSL 2 |
| Linux发行版 | Ubuntu 26.04 |
| Docker Engine | 29.6.1 |
| Docker Compose | v5.3.0 |
| RAGFlow | v0.26.4 |
| 部署模式 | Docker Compose CPU模式 |
| Python | 3.14.4 |

RAGFlow官方建议至少准备4核CPU、16 GB内存和50 GB磁盘，并使用Docker 24.0.0及以上、Docker Compose v2.26.1及以上版本。

## 2. 部署架构

```text
Windows 11
├── VS Code / Git
├── WSL 2
│   └── Ubuntu
│       └── RAGFlow源代码与Docker Compose配置
└── Docker Desktop
    ├── RAGFlow
    ├── MySQL
    ├── Elasticsearch
    ├── Valkey
    └── MinIO
```

本项目仓库只保存领域数据目录、配置示例、评测脚本、评测结果和项目文档，不复制RAGFlow源码及其运行数据。

## 3. 前置检查

在PowerShell中确认WSL和Docker可用：

```powershell
wsl -l -v
docker --version
docker compose version
docker info --format "{{.OSType}}"
```

正常情况下，Ubuntu的WSL版本应为 `2`，Docker容器类型应为：

```text
linux
```

检查Elasticsearch所需参数：

```powershell
wsl -d docker-desktop -u root sysctl vm.max_map_count
```

该值应不低于：

```text
262144
```

如果数值不足，可临时设置：

```powershell
wsl -d docker-desktop -u root sysctl -w vm.max_map_count=262144
```

Docker Desktop重启后应重新检查该值。

## 4. 部署RAGFlow

进入Ubuntu后克隆RAGFlow官方仓库：

```bash
git clone https://github.com/infiniflow/ragflow.git
cd ragflow
git checkout v0.26.4
cd docker
```

确认 `docker/.env` 中使用与源码一致的RAGFlow镜像版本，然后启动CPU模式：

```bash
docker compose -f docker-compose.yml up -d
```

查看容器状态：

```bash
docker compose ps
```

查看RAGFlow服务日志：

```bash
docker logs -f docker-ragflow-cpu-1
```

全部服务启动后，在浏览器访问：

```text
http://localhost
```

## 5. 已验证容器

| 服务 | 已验证镜像 |
|---|---|
| RAGFlow | `infiniflow/ragflow:v0.26.4` |
| MySQL | `mysql:8.0.39` |
| Valkey | `valkey/valkey:8` |
| Elasticsearch | `elasticsearch:8.11.3` |
| MinIO | `pgsty/minio:RELEASE.2026-03-25T00-00-00Z` |

实际运行状态参见：

```text
docs/screenshots/01-docker-containers.png
```

## 6. RAGFlow模型与知识库配置

在RAGFlow管理界面中配置：

- LLM：在线大语言模型API
- Embedding：BGE-M3或兼容的向量模型
- Rerank：qwen3-rerank
- 相似度阈值：0.2
- 向量相似度权重：0.50
- 全文相似度权重：0.50
- Top N：8

API Key应通过RAGFlow模型供应商配置页面或本地环境变量设置，不得写入README、截图或Git提交。

知识库导入5份医疗器械软件监管资料后，应确认：

- 文档解析完成；
- 知识片段已启用；
- 检索测试能够返回正确条款；
- 问答结果能够展示来源引用。

## 7. 批量评测环境

在项目根目录创建Python虚拟环境：

```powershell
py -3.14 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

在本地 `.env` 中填写RAGFlow地址、API Key和助手名称。真实 `.env` 已由 `.gitignore` 排除。

验证连接：

```powershell
python scripts/check_connection.py
```

运行50题批量检索评测：

```powershell
python scripts/run_batch_eval.py --label final
```

运行自动裁判：

```powershell
python scripts/run_judge_eval.py
```

## 8. 验证标准

部署成功应满足：

- Docker Engine能够运行Linux容器；
- RAGFlow、MySQL、Elasticsearch、Valkey和MinIO均处于运行状态；
- 浏览器能够访问RAGFlow；
- Python脚本能够连接指定聊天助手；
- 50道评测问题均成功执行；
- 回答能够返回来源引用；
- `.env` 和API Key没有进入Git版本记录。

## 9. 常见问题

### PowerShell禁止激活虚拟环境

仅对当前PowerShell进程临时允许脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
```

### RAGFlow页面无法访问

依次检查：

```powershell
docker compose ps
docker logs docker-ragflow-cpu-1
```

等待RAGFlow完成初始化后再刷新浏览器。

### Elasticsearch无法启动

重新检查：

```powershell
wsl -d docker-desktop -u root sysctl vm.max_map_count
```

### API连接失败

确认：

- Docker Desktop和RAGFlow正在运行；
- `.env` 中的基础地址正确；
- API Key仍然有效；
- 助手名称与RAGFlow界面完全一致。

## 10. 安全注意事项

- 不提交真实 `.env`、API Key、密码或证书；
- 不提交Docker运行数据、数据库文件或向量索引；
- 截图前隐藏用户名称、本地路径和账户信息；
- 监管资料应记录来源和版本；
- 回答仅用于研究与测试，不能替代正式监管文件。