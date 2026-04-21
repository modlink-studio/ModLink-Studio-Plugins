# Palm Sensor Driver

本驱动把手掌传感器接入 `ModLink Studio`，并向宿主提供 `10x10` 的 `field` 流。

## 接入方式

- 通过 `modlink-plugin install palm-sensor` 安装到当前环境
- entry point：`palm-sensor`
- 当前实现基于串口读取原始字节流，并在驱动内完成拆帧、拼帧和矩阵重排

## 当前能力

- 通过 `modlink.drivers` entry point 被宿主发现
- `search()` 支持 `serial`
- `LoopDriver` 负责基于 runtime 周期调度的串口轮询
- 输出固定 shape 为 `[1, 1, 10, 10]` 的 `field` payload
- 可通过代码中的 bool 开关启用软件归零

## 串口参数

- 波特率：`921600`
- 数据位：`8`
- 校验位：`N`
- 停止位：`1`
- 读取模式：`timeout=0`

## 解析规则摘要

- 帧头固定为 `AA 55`
- 长帧 `0x02`，长度 `150`，负责前 `8` 行
- 短帧 `0x01`，长度 `134`，负责后 `2` 行
- 只有长帧和短帧都在上次输出后更新过，才会上送新的完整矩阵
- 每行都会执行列映射 `10 9 8 7 6 1 2 3 4 5`

## 软件归零

- 默认关闭
- 如需启用，直接修改 `palm_sensor/driver.py` 中的 `ENABLE_ZERO_BASELINE = True`
- 启用后，连接设备后的第一张完整 `10x10` 矩阵会被记为零点基线

## 安装方式

```bash
modlink-plugin install palm-sensor
```

## 在仓库里联调

```bash
uv pip install --python .venv/Scripts/python.exe --no-deps -e plugins/palm-sensor
```
