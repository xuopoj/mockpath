# mockpath

[![PyPI](https://img.shields.io/pypi/v/mockpath)](https://pypi.org/project/mockpath/)

轻量级 HTTP Mock 服务器。通过 YAML 配置 + JSON 文件定义模拟接口，目录结构即 URL 路径。

## 特性

- 目录结构自动映射为 URL 路径
- YAML 定义接口配置，JSON 定义请求/响应体
- 支持 query 参数匹配（子集匹配，请求中的额外参数不影响匹配）
- 支持请求体匹配（深度相等比较）
- 请求体和响应体均支持内联、文件引用、约定命名三种方式
- `--reload` 模式自动监听文件变更并热重载
- 未知路径返回 404，方法不匹配返回 405

## 安装

```bash
pip install mockpath
```

或使用 uv：

```bash
uv tool install mockpath
```

## 使用

```bash
mockpath [-p PORT] [-d DIR] [--reload]
```

| 参数 | 说明 | 默认值 |
|---|---|---|
| `-p, --port` | 监听端口 | 8000 |
| `-d, --dir` | 配置目录 | `./api` |
| `--reload` | 监听文件变更，自动重载配置 | 关闭 |
| `--version` | 显示版本号 | |
| `--help` | 显示帮助信息 | |

## 文件命名规则

```
api/                              # 配置根目录（通过 -d 指定）
  v1/
    users/
      list.get.yaml               # GET /v1/users/list 的配置
      list.get.resp.json           # 默认响应
      list.get.resp.1.json         # 匹配规则 #1 的响应
      profile.post.yaml            # POST /v1/users/profile 的配置
      profile.post.resp.json       # 默认响应
      profile.post.req.1.json      # 匹配规则 #1 的请求体
      profile.post.resp.1.json     # 匹配规则 #1 的响应
```

命名模式：`<端点名>.<HTTP方法>.yaml`

## YAML 配置格式

### 基础接口（无匹配规则）

```yaml
# profile.get.yaml
status: 200
```

响应体来自 `profile.get.resp.json`。

### Query 参数匹配

```yaml
# list.get.yaml
status: 200
matches:
  - params:
      page: "1"
      limit: "10"
  - params:
      page: "2"
    response:               # 内联响应
      users: []
      total: 0
```

匹配逻辑：请求的 query 参数是配置参数的超集即可匹配（子集匹配）。

### 请求体匹配（POST/PUT/PATCH）

```yaml
# profile.post.yaml
status: 201
matches:
  - request:                 # 内联请求体
      name: "Bob"
    response_file: resp.1.json
  - request_file: req.2.json # 引用外部请求体文件
    response:
      id: 4
      name: "Alice"
  - status: 200              # 约定命名：请求体来自 profile.post.req.3.json
```

### 请求体的三种指定方式

每条匹配规则的请求体按以下优先级确定：

1. **`request`** — YAML 中的内联 JSON 请求体
2. **`request_file`** — 引用外部文件（相对于 YAML 文件的路径）
3. **约定命名** — 自动查找 `<端点名>.<方法>.req.N.json`

### 响应的三种指定方式

每条匹配规则的响应按以下优先级确定：

1. **`response`** — YAML 中的内联 JSON 响应
2. **`response_file`** — 引用外部文件（相对于 YAML 文件的路径）
3. **约定命名** — 自动查找 `<端点名>.<方法>.resp.N.json`

## 匹配流程

1. 按 `matches` 列表顺序逐一尝试
2. **第一个匹配成功的规则生效**（first match wins）
3. 无匹配 → 返回默认响应

## 示例

```bash
# 启动服务器
mockpath -p 3000

# Query 参数匹配
curl "http://localhost:3000/v1/users/list?page=1"
# → [{"id": 1, "name": "Alice"}]

curl "http://localhost:3000/v1/users/list?page=2"
# → {"users": [], "total": 0}

# 请求体匹配
curl -X POST http://localhost:3000/v1/users/profile \
  -H "Content-Type: application/json" \
  -d '{"name": "Bob"}'
# → {"id": 3, "name": "Bob"}

# 无匹配时返回默认响应
curl "http://localhost:3000/v1/users/list"
# → [{"id": 1, "name": "Alice"}]
```

## 依赖

- Python >= 3.10
- [PyYAML](https://pyyaml.org/)
- [Click](https://click.palletsprojects.com/) >= 8.0
