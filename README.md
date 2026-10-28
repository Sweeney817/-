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
