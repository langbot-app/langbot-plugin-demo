# AI 绘图插件

## 简介

兼容使用 OpenAI 格式的绘图插件，支持任何兼容 OpenAI 图片生成 API 的服务。

## 功能特性

- ✅ 完全兼容 OpenAI 图片生成 API 格式
- 🎨 支持自定义 API 地址和模型名称
- 📐 支持多种图片尺寸比例
- 🔧 灵活的配置选项

## 配置说明

### API 配置

- **API 地址**：默认为 `https://api.qhaigc.net`，可自定义为其他兼容 OpenAI 格式的 API 地址
- **API 密钥**：从 [https://api.qhaigc.net/console/token](https://api.qhaigc.net/console/token) 获取
- **模型名称**：可输入自定义模型名称，默认为 `qh-draw-x1-pro`

### 图片尺寸选项

支持以下图片尺寸：

- 正方形 1:1 (1024x1024)
- 正方形 1:1 (1280x1280)
- 竖版 3:5 (768x1280)
- 横版 5:3 (1280x768)
- 竖版 9:16 (720x1280)
- 横版 16:9 (1280x720)
- 横版 4:3 (1024x768)
- 竖版 3:4 (768x1024)

## 使用方法

使用 `!draw` 命令生成图片：

```bash
# 生成图片
!draw 一个美丽的日落风景
!draw 一只坐在彩虹上的猫
```

## 安装步骤

1. 在 LangBot 插件管理页面安装本插件
2. 获取 API Key: [https://api.qhaigc.net/console/token](https://api.qhaigc.net/console/token)
3. 在插件配置中填入 API Key
4. 配置 API 地址、模型名称和默认图片尺寸（可选）

## 兼容性

本插件兼容任何遵循 OpenAI 图片生成 API 规范的服务，包括但不限于：

- OpenAI DALL-E 3
- 其他兼容 OpenAI 格式的图片生成服务

## 许可证

MIT License