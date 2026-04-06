# OpenBCI Ganglion Driver

本驱动把 OpenBCI Ganglion 设备接入 `ModLink Studio`，并向宿主提供 EEG `signal` 流。

## 接入方式

- 通过 `modlink-plugin install openbci-ganglion` 安装到当前环境
- 当前这一条安装命令属于 `modlink-plugin` 的第一阶段能力；后续会被并入更完整的插件管理流程
- entry point：`openbci-ganglion`

## 当前能力

- 通过 `modlink.drivers` entry point 被宿主发现
- `search()` 支持 `ble` 和 `serial`
- `LoopDriver` 负责基于 runtime 周期调度的轮询和流生命周期
- 输出固定 chunk 的 EEG `signal` payload

当前驱动实现已经跟随 `0.2.0` 主线迁移到纯 Python runtime，不再依赖 Qt signal 或 `QTimer`。

## 适用场景

- OpenBCI Ganglion EEG 接入
- 官方 BrainFlow 轮询式 driver 示例
- EEG 预览和采集流程联调

## 安装方式

```bash
modlink-plugin install openbci-ganglion
```

## 在仓库里联调

```bash
uv run python -m pip install -e plugins/openbci-ganglion
```
