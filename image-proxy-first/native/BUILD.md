# 原生程序与可复现构建

正常使用预编译程序，不在安装或首次运行时编译。Windows 和 Linux 各提供 x64、ARM64 文件；Linux 使用静态链接的标准运行库，适用于对应处理器的 Ubuntu 等 Linux 系统。实际运行验证范围以构建清单和测试报告为准，交叉编译不等于已在目标系统实际运行。

自有代码为 `image_proxy.cpp`，依赖固定提交的图像解码、缩放和编码头文件，来源和散列见 `dependencies.json`；第三方许可为 `vendor/LICENSE`，各头文件也保留原许可。

构建工具为 Zig 0.17.1。在本目录的父目录执行以下命令，把目标与输出名替换为需要的平台：

```text
zig c++ -std=c++17 -O3 -DNDEBUG -s -target x86_64-windows-gnu native/image_proxy.cpp -lshell32 -o bin/windows-x64/image-proxy.exe
zig c++ -std=c++17 -O3 -DNDEBUG -s -target aarch64-windows-gnu native/image_proxy.cpp -lshell32 -o bin/windows-arm64/image-proxy.exe
zig c++ -std=c++17 -O3 -DNDEBUG -s -target x86_64-linux-musl -static native/image_proxy.cpp -o bin/linux-x64/image-proxy
zig c++ -std=c++17 -O3 -DNDEBUG -s -target aarch64-linux-musl -static native/image_proxy.cpp -o bin/linux-arm64/image-proxy
```

不使用仅适合构建机处理器的优化目标；不要求新款处理器专有指令。预编译清单见 `builds.json`。文件散列用于完整性核验，不是发布者签名。

一次调用内部负责：输入限额检查、解码及方向处理、原图坐标裁剪、缩放、多档质量与必要的尺寸下降、逐文件体积验证和独占落盘。标准输出只有元数据，绝无图像编码。故障保留已生成文件，但在完整完成前不发布成功清单。解码内存取决于源像素；代理体积上限不等于解码内存上限。
