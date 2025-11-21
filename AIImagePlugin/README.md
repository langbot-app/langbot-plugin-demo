# AI Image Generation Plugin

## Introduction

A drawing plugin compatible with OpenAI format, supporting any service that implements the OpenAI image generation API.

## Features

- Fully compatible with OpenAI image generation API format
- Support for custom API endpoint and model names
- Multiple image aspect ratio options
- Flexible configuration options

## Configuration

### API Configuration

- **API Endpoint**: Default is `https://api.qhaigc.net`, can be customized to other OpenAI-compatible API endpoints
- **API Key**: Obtain from [https://api.qhaigc.net/console/token](https://api.qhaigc.net/console/token)
- **Model Name**: Can input custom model name, default is `qh-draw-x1-pro`

### Image Size Options

Supports the following image sizes:

- Square 1:1 (1024x1024)
- Square 1:1 (1280x1280)
- Portrait 3:5 (768x1280)
- Landscape 5:3 (1280x768)
- Portrait 9:16 (720x1280)
- Landscape 16:9 (1280x720)
- Landscape 4:3 (1024x768)
- Portrait 3:4 (768x1024)

## Usage

Use the `!draw` command to generate images:

```bash
# Generate images
!draw a beautiful sunset landscape
!draw a cat sitting on a rainbow
```

## Installation Steps

1. Install this plugin from the LangBot plugin management page
2. Obtain API Key: [https://api.qhaigc.net/console/token](https://api.qhaigc.net/console/token)
3. Enter the API Key in the plugin configuration
4. Configure API endpoint, model name, and default image size (optional)

## Compatibility

This plugin is compatible with any service that follows the OpenAI image generation API specification, including but not limited to:

- OpenAI DALL-E 3
- Other OpenAI-compatible image generation services

## License

MIT License