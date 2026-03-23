# hardware

该目录提供 ESP32 设备侧示例代码与示例配置。

## 文件说明

- `esp32.example.ino`：脱敏后的 ESP32 示例草图
- `.env.example`：硬件相关占位配置清单，便于统一管理敏感项

## 使用方式

1. 复制 `esp32.example.ino` 为本地私有文件，例如 `esp32.ino`
2. 参考 `.env.example` 中的占位项，手动填入 WiFi、MQTT、NTP 等真实配置
3. 不要把真实凭据版草图重新提交到公开仓库
