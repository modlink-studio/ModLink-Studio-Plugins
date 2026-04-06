# Host Microphone Driver

本驱动把本机麦克风输入接入 `ModLink Studio`，并向宿主提供音频波形流。

## 接入方式

- 通过 `modlink-plugin install host-microphone` 安装到当前环境
- 当前这一条安装命令属于 `modlink-plugin` 的第一阶段能力；后续会被并入更完整的插件管理流程
- entry point：`host-microphone`

## 适用场景

- 本机音频输入预览
- 音频采集链路联调
- 作为官方示例音频驱动进行开发联调

## 安装方式

```bash
modlink-plugin install host-microphone
```

## 在仓库里联调

```bash
uv run python -m pip install -e plugins/host-microphone
```
