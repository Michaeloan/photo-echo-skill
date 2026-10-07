<div align="center">

# Photo Echo · 照片回声

**把旅途里有特点的一小块画面，留下来。**

原照片 · 局部小景 · 克制微动

[看效果](#看效果) · [设计方法](#怎样选景怎样排版) · [安装与使用](#安装与使用) · [输出说明](#会得到什么)

</div>

---

一张旅行照片里，最值得记住的可能是湖中的一棵小树、横枝和它的倒影，也可能是一段屋檐与台阶的关系。这个skill先找到那块有辨识度的画面，把它画成精巧的小景，放在原照片下方，再让叶端或水纹轻轻动起来。

照片保留真实观看的分量，插画承担较轻的记忆回应。AI负责取景分析和插画，本机脚本负责拼版、动画与文件导出。

## 看效果

<p align="center">
  <img src="assets/examples/05-island/cover.jpg" width="540" alt="真实九寨沟照片手帐：原片铺满上半幅，小植物岛与倒影插画位于下半留白">
</p>

<p align="center"><em>Still water · 原片在上，小景在下</em></p>

这个例子来自真实的九寨沟旅行照片。插画选择水中的小植物岛、短沉木和紧邻倒影；远岸森林与山壁留在原片中。下方小景约300×302px，整体画布1080×1440，纸面保留大面积空白。

### 七张真实作品

<p align="center">
  <img src="assets/gallery.jpg" width="960" alt="七张已确认真实手帐：云影湖湾、枝端入水、云影与枝框、沉木水光、植物小岛、亮树与倒影、叶端与湖光">
</p>

七张原片各自选择不同的局部关系，没有统一套成同一个小树模板。

| 作品 | 选中的特色画面 | 完整成品 |
| --- | --- | --- |
| 云影湖湾 | 湖湾、云影与相邻林岸的弧线关系 | [封面](assets/examples/01-cloud-bay/cover.jpg) · [MP4](assets/examples/01-cloud-bay/preview.mp4) |
| 枝端入水 | 枝条分叉端与紧邻蓝绿水面 | [封面](assets/examples/02-branch-water/cover.jpg) · [MP4](assets/examples/02-branch-water/preview.mp4) |
| 云影与枝框 | 枝叶框景与水中云影 | [封面](assets/examples/03-cloud-branch/cover.jpg) · [MP4](assets/examples/03-cloud-branch/preview.mp4) |
| 沉木水光 | 水下沉木分叉和水面光痕 | [封面](assets/examples/04-submerged-wood/cover.jpg) · [MP4](assets/examples/04-submerged-wood/preview.mp4) |
| 植物小岛 | 小植物岛、短沉木与紧邻倒影 | [封面](assets/examples/05-island/cover.jpg) · [MP4](assets/examples/05-island/preview.mp4) |
| 亮树与倒影 | 一簇亮树及其直接倒影 | [封面](assets/examples/06-tree-reflection/cover.jpg) · [MP4](assets/examples/06-tree-reflection/preview.mp4) |
| 叶端与湖光 | 叶端、相邻湖光与少量水纹 | [封面](assets/examples/07-leaf-light/cover.jpg) · [MP4](assets/examples/07-leaf-light/preview.mp4) |

也可以看 [七张动态总览](assets/gallery.mp4)。

### 从整张照片，走到实际取景

| 示例输入 | 插画使用的实际局部 |
| :---: | :---: |
| <img src="assets/examples/05-island/source.jpg" width="440" alt="真实原片公开缩图：小植物岛位于湖中，周围有森林与山壁"> | <img src="assets/examples/05-island/reference.jpg" width="265" alt="真实插画取景参考：小植物岛、短沉木与紧邻倒影"> |

取景决定了插画的信息量。保留树根、横枝、水线和倒影，才是一块可以读懂的画面；需要更多环境时，再有理由地扩大。

### 动起来的是局部

<p align="center">
  <img src="assets/examples/05-island/motion.gif" width="560" alt="植物小岛成品MP4下半幅：仅根部水纹和下方倒影轻微变化，岸上植物和沉木固定">
</p>

GIF放大展示下半幅：连续水纹与叶端轻摆分成两个区域，主干、根部和短沉木有保护笔迹。完整视频里的上半照片、纸面和标题固定。查看 [完整三秒MP4](assets/examples/05-island/preview.mp4) 或 [制作检查记录](assets/examples/05-island/report.json)。

动态更新使用连续形变，运动在边缘平滑归零，只采样一次，避免原线条与移位线条叠出重影。水纹持续推进，叶端依连接位置轻摆；位移与局部形变均有限制。可以看 [三版动态对比](assets/motion-comparison.mp4)：从左至右是原版、连续水纹、叶端轻摆＋水纹。

当前助手提供的是本机笔触微动，没有接入视频生成模型。它改善衔接与重影，但不重建真实水体、布料或叶片的时间变化。自然程度要求更高时，应评估学习流场、分层动画或受控图生视频，见 [动态后端与质量边界](references/natural-motion.md)；这些增强后端尚未随仓库提供可运行集成。

| 枝端入水 · 局部水纹 | 亮树与倒影 · 局部倒影 |
| :---: | :---: |
| <img src="assets/examples/02-branch-water/motion.gif" width="390" alt="枝端入水成品的局部微动"> | <img src="assets/examples/06-tree-reflection/motion.gif" width="390" alt="亮树与倒影成品的局部微动"> |

> 全部展示来自维护者授权公开的七张真实照片。插画由Luna编排生图工具制作，排版和局部动画在本机完成。植物小岛的运动现已改为连续水纹＋叶端轻摆，原片、插画与排版沿用原版本，其余六张保留已确认成品。更新未重新生图；公开原片与参考图已縮小并去除EXIF。GIF用于预览，Apple配对检查与手机实测分别记录。

## 怎样选景，怎样排版

### 一块有特点的连续画面

先找主体的特色局部，再补必要的连接关系：树与水线、船与岸、屋檐与台阶、枝条与倒影。没有醒目的主体时，山脊交叠、岸湾转折与云影也可以成为小景核心。

从最小可读范围出发。若关系被截断，或缩小后不能辨认，才逐渐扩大，并保存理由与参考裁片供检查。每张照片独立选择，不套用示例的坐标和对象。

### 照片、插画和留白各有分量

默认画布1080×1440，上半原照片、下半近白纸面各占一半。照片铺满上半，纸面只出现在下半；没有整页米白外框、撕纸边或多余装饰。

插画以细而断续的结构线、少量源图颜色和疏松印刷痕迹形成层次。主锚点更清楚，辅助环境逐渐消失。按可见墨痕控制大小和视觉重心，密实图案进一步缩小。

| 默认设计 | 数值与含义 |
| --- | --- |
| 画布 | 1080×1440，上下各720px |
| 小景尺度 | 初始宽≤43%整幅宽，高≤42%下半高；是上限，不是填满目标 |
| 位置 | 下半视觉重心约55%，横向随主景适度偏置 |
| 色彩 | 两至四种主要源图颜色，细线与空白保留结构 |
| 文字 | 可选单行小标题，不推测日期地点 |
| 动画 | 最多两个局部区域，默认3秒、30fps |

竖照片等比裁入上半窗口，可以调焦点；源文件完整保留。3:2横照片可完整填入默认窗口。用户明确指定比例和构图时，skill沿用该选择。

详细规则见 [比例与审美](references/layout-and-style.md)。

## 安装与使用

### 怎么用

给Codex一张或一组图片，直接说：

```text
使用 $photo-echo，把这些图片做成手帐，结果放在一起。
```

也可以直接给图片路径或明确指定输出位置。取景、插画、轻量运动和文件整理由skill完成，不需要用户填写选区、运动计划、模型参数或逐张输出目录。

一次输入对应一个结果目录。默认在第一张原图旁创建 **Photo Echo** 文件夹；聊天附件没有原目录时，保存到当前工作区。来自不同位置的图片也集中输出，每张按原文件名对应命名，同名自动加序号。

插画使用Codex实际可用的生图能力，动态保持本机轻量微动。不会自动安装大视频模型或增加付费视频服务。已有插画可以复用，本机调整不重复生图。

### 安装skill

将仓库放入Codex的skills目录，保持目录名 `photo-echo`。安装后刷新技能列表或重新打开会话。

**Windows PowerShell**

```powershell
git clone https://github.com/Michaeloan/photo-echo-skill.git "$env:USERPROFILE/.codex/skills/photo-echo"
```

**macOS／Linux**

```sh
git clone https://github.com/Michaeloan/photo-echo-skill.git "$HOME/.codex/skills/photo-echo"
```

自定义CODEX_HOME时，改用对应的skills目录。当前skill名为 `$photo-echo`，原仓库保留历史并由GitHub转向新名称。

<details>
<summary>开发者：复现公开素材与本机参数</summary>

日常使用只需给图片。下面是内部助手的复现方式，任务清单已随真实样例提供，无需手填：

```sh
python -m pip install -r requirements.txt
python scripts/photo_echo.py batch --jobs assets/examples/jobs.json --out outputs/PhotoEcho
```

这条命令复用三张真实照片及现成插画，一次渲染并把三组PNG／MP4放在同一目录。公开原图已缩小，渲染器版本也有差异，复现不承诺与展示成品逐像素相同。

内部助手只做本机制作，不调用模型。需要静态图时增加 `--still`；Apple资源使用 `--apple`。视频需要FFmpeg，imageio-ffmpeg可提供普通照片路线编码器；原Live另需ffprobe；Apple封装另需Live Photo Box CLI与ExifTool。

中文标题优先使用系统中文字体，亦可设置 `PHOTO_ECHO_FONT`。原LIVE_HANDBOOK环境变量保持兼容。调整焦点、大小、强度和封面仍使用各张自己的素材和参数，见 [内部输出与导出说明](references/live-export.md)。

</details>

## 会得到什么

假设输入 `湖湾.jpg` 和 `树影.png`，输出都在一起：

```text
Photo Echo/
├── 湖湾_手帐.png
├── 湖湾_手帐.mp4
├── 树影_手帐.png
├── 树影_手帐.mp4
└── .photo-echo/       内部工作文件，无需逐张整理
```

静态模式只输出PNG。原图完整保留；追加制作不会覆盖旧成品。同名来源自动变为 `湖湾_2_手帐.png` 等，成功项会保留，失败项单独记录并继续处理其余图片。

需要Apple实况时，再增加按原名配对的 `湖湾_实况.JPG` 与 `湖湾_实况.MOV`。默认普通文件夹，无需解压；电脑直接播放MP4即可。

| 输入 | 原照片区域 | 插画区域 |
| --- | --- | --- |
| 静态照片／扫描裁剪图 | 保持静止 | 本机局部微动 |
| 完整原Live配对 | 使用原视频动作、时长与可用音轨 | 同步微动 |
| 缺少MOV的Live静帧 | 提示缺失，按静态处理 | 本机局部微动 |

七张公开作品均来自真实照片。电脑Apple元数据检查与iPhone实机检查分别记录，不把MP4或普通HEIF当作完整Apple实况；手机实机验收尚未进行。详细规则收在 [导出说明](references/live-export.md)。

## 仓库里有什么

| 文件 | 用途 |
| --- | --- |
| [SKILL.md](SKILL.md) | Agent入口：选景、生成、排版、微动和交付 |
| [prompts.md](references/prompts.md) | 三阶段提示词与针对性修正 |
| [layout-and-style.md](references/layout-and-style.md) | 比例、光学重心、密度与关系 |
| [live-export.md](references/live-export.md) | 原Live、Apple检查与批量恢复 |
| [photo_echo.py](scripts/photo_echo.py) | 整批集中输出的本机助手 |
| [assets/](assets/) | 七张真实照片的公开缩图、插画、选区、计划与已确认成品 |
| [sources.md](references/sources.md) | 示例来源、方法参考和许可 |

本仓库提供skill与独立助手，桌面界面、队列按钮和EXE不在此包中。取景与生成由agent处理，本机batch助手一次处理整组、集中输出，单张失败保留已完成成果。

## 参考与许可

研究参考 [Photo Ink Echo](https://github.com/zhouaria28-cloud/photo-ink-echo)、[Photo to Minimal Illustration](https://github.com/iamkong/photo-to-minimal-illustration)、[Photo to Travel Sketch](https://github.com/liigoQi/photo-to-travel-sketch)、[Gathered Scenes Zine](https://github.com/Zeejay0/gathered-scenes-zine-skill) 等公开项目，结合成图与多轮反馈独立整理。未复制作者原始作品或提示词，本仓库模板不宣称是小红书作者原词。

自有代码与文档采用 [MIT License](LICENSE)，真实照片与相应示例的使用范围见 [素材说明](assets/README.md)。外部工具遵守各自许可，不打包二进制。发布自己的作品前确认照片与个人信息的公开授权。

<div align="center">

**让照片留下场景，让小景留下回声。**

</div>
