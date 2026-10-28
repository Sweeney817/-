# 橘子桌面宠物

根据桌面“六六形象素材”更新的 Windows 桌面宠物。使用内置 imagegen 工具生成角色图集，保留写实橘猫、绿色眼睛、粉色鼻子和侧身大块旋涡纹。原参考素材未修改。

- `app.py`：桌面宠物、九种动作、拖动与大小设置。
- `screenshot_tool.py`：原有 F1 截图、贴图和翻译功能。
- `assets/liuliu-source.png`：生成的原始透明动作素材。
- `assets/spritesheet.png`：供程序加载的 768 × 1664 图集。
- `assets/generation-prompt.txt`：完整生成提示词。
- `prepare_assets.cjs`：把生成素材按透明间隔分帧，统一尺寸和脚底基线。
- `verify_pet.py`：验证九种动作、三种尺寸和图集透明边距。
- `build.ps1`：打包为独立程序，生成 `dist/OrangeCatDesktopPet.exe`。

左右走路使用同一组帧镜像，跳跃按起跳到落地的顺序播放。显示大小、位置和置顶设置沿用旧程序。

桌面快捷方式仍指向 `C:\Users\Administrator\Documents\桌面宠物\橘猫桌面宠物\OrangeCatDesktopPet.exe`。

## 使用和构建

右键橘猫可选择陪玩、喝水、休息或打招呼；双击也能打招呼。左键拖动位置，滚轮调整大小，F1 截图。暂停时选择互动会自动恢复活动。

猫咪活动约 3–5 分钟后会自动使用猫砂盆，依次表现排便和埋砂；右键选择“去猫砂盆”也可立即触发。暂停时不会累积等待时间。

新版使用六组六六动作图：猫砂盆、喝水、伸懒腰、揣手休息、打滚和挠痒，可随机出现，也可通过右键菜单触发。更新时显示下载百分比、安装文件复制进度和替换状态。

在 Windows 上安装 Python 和 Pillow 后，可运行 `python app.py`。翻译所需的 OCR 组件为 `rapidocr_onnxruntime`。运行 `powershell -ExecutionPolicy Bypass -File .\build.ps1` 可安装打包依赖并生成 EXE；也可通过环境变量 `ORANGE_CAT_PYTHON` 指定 Python 可执行文件。打包使用仓库中现有的图集，不需要重新生成素材。

开发检查：运行 `python -m unittest test_pet`；`python verify_pet.py` 需要交互式 Windows 桌面，并会生成截图和验证结果。

## 在线更新与发布

打包版启动后会在后台检查 GitHub Release；也可右键选择“检查更新”。发现新版本时可选择下载并安装，程序会校验 SHA256、关闭并重启，原有设置保留。需要网络和 EXE 所在目录的写入权限；校验值用于检查下载完整性，并非代码签名。

发布新版本时，将 `version.py` 的版本号递增并提交到 `main`。GitHub Actions 会构建 Windows EXE，创建对应的 `v版本号` Release，并上传 `OrangeCatDesktopPet.exe` 和 `OrangeCatDesktopPet.exe.sha256`。仓库需要启用 Actions 并允许工作流写入仓库；具体状态请查看 Actions。也可手动运行发布工作流，但同版本的 Release 已存在时不会覆盖它。
