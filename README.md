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

在 Windows 上安装 Python 和 Pillow 后，可运行 `python app.py`。翻译所需的 OCR 组件为 `rapidocr_onnxruntime`。运行 `powershell -ExecutionPolicy Bypass -File .\build.ps1` 可安装打包依赖并生成 EXE；也可通过环境变量 `ORANGE_CAT_PYTHON` 指定 Python 可执行文件。打包使用仓库中现有的图集，不需要重新生成素材。

开发检查：运行 `python -m unittest test_pet`；`python verify_pet.py` 需要交互式 Windows 桌面，并会生成截图和验证结果。
