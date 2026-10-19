# pydantic-core 的 Android wheel（手工构建）

Chaquopy 官方包仓库（<https://chaquo.com/pypi-13.1>）**没有** `pydantic` / `pydantic-core`，
而 `pydantic` 又硬性依赖 `pydantic-core`（Rust 扩展），所以必须自己编一份 Android 版 wheel。

这里的两个文件就是编好的成品（CPython 3.13、minSdk 29）：

| 文件 | ABI |
| --- | --- |
| `pydantic_core-2.50.1-cp313-cp313-android_29_x86_64.whl` | x86_64（模拟器） |
| `pydantic_core-2.50.1-cp313-cp313-android_29_arm64_v8a.whl` | arm64-v8a（真机） |

`app/build.gradle.kts` 里用 `options("--find-links=<本目录绝对路径>")` 让 Chaquopy 的 pip 从这里取；
`pydantic==2.14.1` 其它纯 Python 依赖（annotated-types / typing-inspection / typing-extensions）仍从 PyPI 装。

## 重新构建（Windows 主机）

前置：Rust（`rustup target add x86_64-linux-android aarch64-linux-android`）、NDK（27.2.x）、
以及从 Chaquopy 的 Python 发行包里拿到的 `libpython3.13.so`（arm64 / x86_64 各一份，用于链接）。

1. 取 sdist：`https://pypi.org/pypi/pydantic_core/2.50.1/json` 里的 `pydantic_core-2.50.1.tar.gz`，解压。
2. 依次交叉编译（示例 x86_64）：

```powershell
$tc = "$env:LOCALAPPDATA\Android\Sdk\ndk\27.2.12479018\toolchains\llvm\prebuilt\windows-x86_64\bin"
$env:PYO3_CROSS = "1"; $env:PYO3_CROSS_PYTHON_VERSION = "3.13"
$env:CARGO_TARGET_X86_64_LINUX_ANDROID_LINKER = "$tc\clang.exe"
$env:CARGO_TARGET_X86_64_LINUX_ANDROID_RUSTFLAGS = "-C link-arg=--target=x86_64-linux-android29 -C link-arg=-fuse-ld=lld -C link-arg=-L<libpython 所在目录>"
cargo build --release --target x86_64-linux-android --features pyo3/extension-module
```

要点：
- 必须加 `--features pyo3/extension-module`，否则 pyo3 会去找 `-lpython3.13`；
- Android 目标即使开了 extension-module 也仍会链接 `libpython3.13.so`，所以用 `-L` 指向从
  `~/.gradle/caches/modules-2/files-2.1/com.chaquo.python/target/3.13.0-1/*/target-3.13.0-1-<abi>.zip`
  里解出来的 `jniLibs/<abi>/libpython3.13.so`。
3. 组装 wheel（纯 Python 部分 + `_pydantic_core.so` + dist-info）：

```bash
python scripts/assemble_pydantic_wheel.py pydantic_core-2.50.1 \
  pydantic_core-2.50.1/target/x86_64-linux-android/release/lib_pydantic_core.so \
  android_29_x86_64 .
```

4. 把产出的 `.whl` 放进本目录，重新 `gradle assembleDebug` 即可。

> 升级 pydantic 时注意：`pydantic` 的每个版本都钉死一个 `pydantic-core` 版本，两者要一起换。
