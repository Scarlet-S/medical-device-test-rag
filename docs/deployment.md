# RAGFlow Deployment Record

## Deployment Environment

| Component | Configuration |
|---|---|
| Operating System | Windows 11 64-bit |
| CPU | Intel Core Ultra 9 275HX |
| Memory | 31.5 GB |
| Linux Environment | WSL 2 |
| Linux Distribution | Ubuntu 26.04 LTS |
| Docker Desktop | 4.82.0 |
| Docker Engine | 29.6.1 |
| Docker Compose | 5.3.0 |
| RAGFlow | v0.26.4 |
| Deployment Mode | Docker Compose, CPU mode |

## Storage Locations

- Ubuntu distribution: `D:\Tools\CodeTools\WSL\Ubuntu`
- Docker data: `D:\Tools\CodeTools\DockerDesktopData\DockerDesktopWSL`
- Personal project repository: `D:\Tools\CodeTools\Projects\medical-device-test-rag`
- RAGFlow source code: `/home/momo/ragflow`

## Running Services

The following Docker containers were successfully deployed:

- RAGFlow application
- MySQL
- Elasticsearch
- Redis
- MinIO

## Verification

- Docker Engine successfully ran the `hello-world` container.
- Docker commands were available inside Ubuntu through WSL integration.
- All RAGFlow-related containers entered the running state.
- The RAGFlow web interface was successfully accessed through `http://localhost`.

## Deployment Architecture

```text
Windows 11
├── Git repository
│   └── medical-device-test-rag
├── WSL 2
│   └── Ubuntu
│       └── RAGFlow v0.26.4 source code
└── Docker Desktop
    ├── RAGFlow
    ├── MySQL
    ├── Elasticsearch
    ├── Redis
    └── MinIO# RAGFlow Deployment Record

## Deployment Environment

| Component | Configuration |
|---|---|
| Operating System | Windows 11 64-bit |
| CPU | Intel Core Ultra 9 275HX |
| Memory | 31.5 GB |
| Linux Environment | WSL 2 |
| Linux Distribution | Ubuntu 26.04 LTS |
| Docker Desktop | 4.82.0 |
| Docker Engine | 29.6.1 |
| Docker Compose | 5.3.0 |
| RAGFlow | v0.26.4 |
| Deployment Mode | Docker Compose, CPU mode |

## Storage Locations

- Ubuntu distribution: `D:\Tools\CodeTools\WSL\Ubuntu`
- Docker data: `D:\Tools\CodeTools\DockerDesktopData\DockerDesktopWSL`
- Personal project repository: `D:\Tools\CodeTools\Projects\medical-device-test-rag`
- RAGFlow source code: `/home/momo/ragflow`

## Running Services

The following Docker containers were successfully deployed:

- RAGFlow application
- MySQL
- Elasticsearch
- Redis
- MinIO

## Verification

- Docker Engine successfully ran the `hello-world` container.
- Docker commands were available inside Ubuntu through WSL integration.
- All RAGFlow-related containers entered the running state.
- The RAGFlow web interface was successfully accessed through `http://localhost`.

## Deployment Architecture

```text
Windows 11
├── Git repository
│   └── medical-device-test-rag
├── WSL 2
│   └── Ubuntu
│       └── RAGFlow v0.26.4 source code
└── Docker Desktop
    ├── RAGFlow
    ├── MySQL
    ├── Elasticsearch
    ├── Redis
    └── MinIO