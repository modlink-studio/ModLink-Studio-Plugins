# Host Camera Driver

本驱动把本机内置或外接摄像头接入 `ModLink Studio`，并向宿主提供视频流。

## 接入方式

- 通过 `modlink-plugin install host-camera` 安装到当前环境
- 当前这一条安装命令属于 `modlink-plugin` 的第一阶段能力；后续会被并入更完整的插件管理流程
- entry point：`host-camera`

## 适用场景

- 本机摄像头预览
- 视频流接入与录制
- 作为官方示例视频驱动进行开发联调

## 安装方式

```bash
modlink-plugin install host-camera
```

## 在仓库里联调

```bash
uv run python -m pip install -e plugins/host-camera
```
