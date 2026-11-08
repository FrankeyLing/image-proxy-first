# 先压缩，再查看图像

全局 Codex 技能：原生 C++ 程序用一条命令生成小体积代理、元信息和常用切图，下一次工具调用直接查看所需代理。不会把原始图像编码打印进工具文本。

## 安装

下载并解压 Releases 中的便携包，或克隆本仓库：

- Windows 双击 `INSTALL.cmd`。
- Ubuntu/Linux 执行 `bash install.sh`。
- 已有同名技能时，Windows 使用 `install.ps1 -ReplaceExisting`，Linux 使用 `bash install.sh --replace-existing`；旧技能会保留在 Codex 用户目录的 `skill-backups` 中。

安装器自动选择 Windows/Linux 的 x64 或 ARM64 预编译版本。正常安装和看图不需要 Python、编译器、管理员权限或联网。默认安装到 `~/.codex/skills/image-proxy-first`，也尊重 `CODEX_HOME`。安装后按需开启新会话或重载技能。

## 两次调用

1. 调用安装后的 `scripts/proxy.cmd`（Windows）或 `scripts/proxy`（Linux）。程序一次处理方向、尺寸、压缩、切图、体积校验和元信息，无需模型逐项计算。
2. 把返回的必要代理路径交给图像查看工具；需要多张时，通过一次工具批调用查看。

```text
proxy <原图>
proxy <原图1> <原图2> --preset fast
proxy <原图> --preset text --layout halves
proxy <原图> --preset detail --layout grid
proxy <长图> --layout strips
proxy <原图> --crop 100 200 1800 900
```

省略输出目录时自动创建唯一临时目录。默认每张代理最多 240,000 字节、最长边 1600 像素；快速模式为 96,000 字节和 1280 像素，详细模式为 300,000 字节和 2048 像素。硬上限 500,000 字节。

元信息包含源尺寸、裁剪坐标、实际体积、耗时、代理路径及可直接调用的其他方案参数数组。只查看需要的代理，不自动把所有预生成分图塞入上下文。原图保留；小字不清时，从原图局部裁剪后再生成代理。

## 格式与验证范围

普通照片、位图和明确布局的 8/16 位工业数据默认走原生程序。工业数据不得猜测宽高、通道顺序、字节序或步长。特殊格式在同一条准备命令内自动回退 Python；可选环境安装方式见英文说明，手机高效格式和厂商相机原始文件需额外解码器，视频还需 ffmpeg。

Windows x64 已本机实测；其他平台已交叉编译及文件格式检查，尚不能视为目标系统实测。源码、构建说明、二进制摘要和本机合成图测试报告均在 `image-proxy-first/native/`。

这是技能规则与本地程序，不是通信拦截器，不能追溯压缩用户已直接附到聊天的图片。代理体积上限不等于解码内存上限，也不能替代原始像素的数值测量。

自有代码和文档使用 MIT 许可；第三方源码及运行库保留原有许可，见 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。
