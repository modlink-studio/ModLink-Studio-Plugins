# ModLink Studio Plugins

ModLink Studio 官方驱动插件仓库。

这个仓库承载：

- 官方驱动源码
- 官方驱动 wheel 发布资产
- 插件索引 `plugins/index.json`
- 后续的插件文档与发布说明

当前官方驱动包括：

- `host-camera`
- `host-microphone`
- `openbci-ganglion`

## Install

主应用仍然通过 PyPI 安装：

```bash
python -m pip install modlink-studio
```

安装官方驱动时，使用主应用自带的插件管理命令：

```bash
modlink-plugin list
modlink-plugin install host-camera
```

## Repository Layout

```text
ModLink-Studio-Plugins/
├─ .github/workflows/
├─ plugins/
│  ├─ index.json
│  ├─ host-camera/
│  ├─ host-microphone/
│  └─ openbci-ganglion/
└─ LICENSE
```

## Development

这个仓库只负责插件源码与发布，不负责主应用发布。

本地联调时，建议先在当前 Python 环境中安装或开发安装 `modlink-studio`，再按需安装某个插件源码包：

```bash
python -m pip install -e plugins/host-camera
python -m pip install -e plugins/host-microphone
python -m pip install -e plugins/openbci-ganglion
```
