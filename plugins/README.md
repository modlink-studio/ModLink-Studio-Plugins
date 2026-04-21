# 插件源目录

`plugins/` 保存的是官方驱动源码和插件索引，不是最终用户的独立 PyPI 安装入口。

从 `0.2.0` 开始，这些插件不会作为独立 PyPI 包公开发布，也不会直接内置到 `modlink-studio` wheel 中。正式安装路径是：

- 先安装 `modlink-studio`
- 再运行 `modlink-plugin install <plugin_id>` 从插件索引解析版本，并从 GitHub Release 安装对应插件 wheel

这个仓库主要用于：

- 官方驱动源码维护
- 本地联调
- GitHub Release 资产构建
- 插件索引维护

当前源码主线面向 `modlink-studio >=0.3.0rc1,<0.4.0`，并已经按当前纯 Python driver API 适配完成，不再依赖旧的 Qt-style runtime 契约。

插件索引会同时保留两条 release 线：

- `>=0.2.0,<0.3.0` 使用历史 wheel
- `>=0.3.0rc1,<0.4.0` 使用当前这套适配 `stream_key` / 新 `FrameEnvelope` 形状的 wheel

## 当前官方驱动

- `host-camera/`
  官方驱动源码：Host Camera
- `host-microphone/`
  官方驱动源码：Host Microphone
- `openbci-ganglion/`
  官方驱动源码：OpenBCI Ganglion
- `palm-sensor/`
  官方驱动源码：Palm Sensor

## 仓库内联调

从 monorepo 根目录运行时，可以把某个驱动源码直接装进当前环境：

```bash
uv pip install --python .venv/Scripts/python.exe --no-deps -e plugins/host-camera
```

```bash
uv pip install --python .venv/Scripts/python.exe --no-deps -e plugins/host-microphone
```

```bash
uv pip install --python .venv/Scripts/python.exe --no-deps -e plugins/openbci-ganglion
```

```bash
uv pip install --python .venv/Scripts/python.exe --no-deps -e plugins/palm-sensor
```
