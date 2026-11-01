# 安装

三种装法，按需选一种。

## 一、命令行（最快，用来验证功能）

```bash
git clone https://github.com/moriruruka/pcrjjc-helper.git
cd pcrjjc-helper

python -m venv .venv
```

激活虚拟环境（Windows：`.venv\Scripts\activate.bat`；macOS / Linux：`source .venv/bin/activate`）。

```bash
# 只要文字查询，约 5 MB
pip install -e ".[lite]"

# 也要“发截图识阵容”，多装 numpy + opencv，约 45 MB
pip install -e ".[full]"

pcrjjc selftest
pcrjjc doctor
```

`selftest` 输出 `15/15 通过` 就说明数据、字体、卡片渲染、解析逻辑都正常。

## 二、AstrBot 插件

### 1. 放进插件目录

```bash
cd <AstrBot>/data/plugins
git clone https://github.com/moriruruka/pcrjjc-helper.git _pcrjjc_tmp
```

把 `_pcrjjc_tmp/astrbot_plugin_pcrjjc` 整个目录复制到 `<AstrBot>/data/plugins/astrbot_plugin_pcrjjc`，然后删掉 `_pcrjjc_tmp`。

> 为什么不能直接 clone 成插件目录：AstrBot 只把「目录名以 `astrbot_plugin_` 开头」的文件夹当成插件，而仓库顶层还要放 `docs/`、`tests/`、`pyproject.toml`。

### 2. 装依赖

```bash
# 用 AstrBot 自己的 Python
<AstrBot>/venv/bin/pip install -r data/plugins/astrbot_plugin_pcrjjc/requirements.txt
```

Windows 上 AstrBot 常见路径是 `<AstrBot>/.venv/Scripts/python.exe`。装完重启 AstrBot，或在面板里重载插件。

### 3. 下载头像

插件启动时会自动检查角色表；头像需要手动拉一次（约 15 MB）：

```bash
# 默认写到插件数据目录
<AstrBot>/venv/bin/pcrjjc avatars

# 也可以显式指定数据目录（推荐：不要把头像放进仓库目录）
<AstrBot>/venv/bin/pcrjjc avatars --data-dir <你自己的数据目录>
```

没有头像时卡片会自动用占位块，功能不中断，只是不好看。

### 4. 首次自检

在群里或私聊发：

```
作业 布丁 克总
```

应该收到一张卡片。如果回的是「没查到作业」，说明网络到 pcrdfans 有问题，看 [TROUBLESHOOTING](TROUBLESHOOTING.md)。

### 5. 数据目录放哪

插件优先用 AstrBot 的插件数据目录（`data/plugin_data/pcrjjc`）。想换位置，设置环境变量：

```bash
PCRJJC_DATA_DIR=D:\pcrjjc-data        # Windows
export PCRJJC_DATA_DIR=/opt/pcrjjc    # Linux
```

## 三、Docker（自建服务时）

镜像里只装核心库与命令行，方便 cron 定时刷新数据：

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[full]"
ENV PCRJJC_DATA_DIR=/data
VOLUME ["/data"]
ENTRYPOINT ["pcrjjc"]
```

```bash
docker build -t pcrjjc .
docker run --rm -v pcrjjc-data:/data pcrjjc selftest
docker run --rm -v pcrjjc-data:/data pcrjjc refresh
```

## 依赖体积参考

| 装法 | 体积 | 能做什么 |
| --- | --- | --- |
| `.[lite]` | ~5 MB | 文字查询、卡片（无头像时占位）、追问逻辑 |
| `.[full]` | ~45 MB | 以上 + 截图识阵容 |
| 头像 | ~15 MB | 卡片上贴真实头像（不装也能用） |

**没有视觉大模型**：截图识别用的是 OpenCV 边缘检测 + 头像脸带的归一化互相关，纯 CPU、纯本地，不需要下载任何模型。
