# 鲸鱼桌宠

一只住在屏幕角落的小鲸鱼。

轮廓不是贴的图——是从 DeepSeek 官方 logo 的矢量路径里逐点解析重绘的，
放大缩小都不糊，尾巴摆动时也是真的在变形。

![预览](assets/preview.png)

## 下载即用（不用装 Python）

到 [Releases](https://github.com/DUDUDU1025/ds-whale-pet/releases) 下载
**`DSWhalePet-v1.0-win64.zip`**（约 21 MB），解压到任意文件夹，双击 `DSWhalePet.exe`。

**卸载 = 删掉那个文件夹。** 不写注册表，不装服务，不留垃圾。
（唯一的例外是开机自启——开了之后会在注册表留一条，右键菜单里关掉就清干净。）

解压后大概是这样：

```
DSWhalePet/
├── DSWhalePet.exe      ← 双击这个
├── _internal/          ← 运行时，别动
└── data/               ← 它记住的东西，删了等于重新认识
```

### 关于杀毒软件

**如果你看到安全警告，这是误报。** 我尽量把它做得不像病毒：

- **不用单文件打包**。单文件 exe 会在运行时把自己解压到 `%TEMP%` 再执行，
  这个行为本来就长得像恶意软件，国内杀软对它的误报率极高。
  这里用的是**文件夹形态**，没有自解压动作。
- **不用 UPX 压缩**。UPX 壳是误报重灾区，宁可体积大一点。
- **不联网、不写注册表（除非你开自启）、不碰你的文件**。
- **源码就在这个仓库里**，`src/whale_pet.py` 一个文件，你可以自己看完再决定跑不跑。

实在不放心的话，直接用下面「从源码跑」的方式——效果完全一样。

## 从源码跑

需要 **Windows** + **Python 3.8 或更高**。程序用了 Win32 的透明窗口、全屏检测和鼠标轮询，
Mac 和 Linux 上跑不了。

```bash
git clone https://github.com/DUDUDU1025/ds-whale-pet.git
cd ds-whale-pet
pip install pillow
python src/whale_pet.py
```

启动后会出现在屏幕**右下角**。想先看它长什么样、但不想开窗口：

```bash
python src/whale_pet.py --preview
```

只用 Pillow 一个依赖。不联网，不要账号，也不读你的文件——唯一的写入是
`data/.whale_state.json`（认识天数、摸头次数、喂食次数）。

### 常见问题

**双击没反应？**
用 `pythonw.exe` 启动就不会弹黑框，但出错也就看不到。装个 `python.exe` 跑一遍看报错。

**它不见了？**
拖到屏幕边缘外会自动拽回来；如果整扇窗都在屏幕外，等一秒它会自己归位。
真找不到了就删掉 `data/.whale_state.json` 里的 `pos` 字段重启。

**想开机自启？**
**右键它 → 「开机自启」**，点一下就行，开了会显示 ✓。再点一下关掉。
写的是当前用户的 Run 键（`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`），
不需要管理员权限，也不用装服务。

程序内置单实例互斥体，开机自启和手动启动撞一起也只会有一只。

**嫌费电？**
改 `src/whale_pet.py` 顶部的 `TARGET_FRAME_MS`（默认 24 → 约 42fps），
或者 `S`（超采样倍率，2 → 1 能省一半 CPU，代价是边缘有锯齿）。
空闲 15 秒会自动降到 12fps，单核占用约 9%，全屏时完全不渲染。

## 它会做什么

- 呼吸浮动、甩尾巴、偶尔喷水、随机眨眼
- 眼睛跟着鼠标转，凑近了会害羞
- 点一下蹦起来，双击跳更高，按住能拖着走
- 30 秒没互动就趴下打瞌睡，开始说梦话
- **睡够 1 分钟会自己醒**；醒了 30 秒还没人理，就**沉到屏幕下面潜水**，几秒后浮回来
- **喂鱼**：右键叼起一条小鱼，鱼跟着光标跑，左键放下——**放在屏幕任何位置都行**，它会游过去吃掉
- **2 分钟没喂鱼会催饭**（最多催 3 次，催完就不烦你了）
- **认出你在用哪个 AI**：切到 DeepSeek 会得意，切到别家会吃醋，能认 26 个（见下）
- 记得认识多少天、被摸过几次、喂过多少条
- 切到全屏游戏时会自动躲开

## 它认得哪些 AI

每隔 1 秒看一眼前台窗口标题。切过去的瞬间扭头、说话，**每句都带名字**：

**自己家**（会得意、冒爱心）

> DeepSeek！是我家！
> 你在用 DeepSeek 呀，我就知道

**别家**（会扭头吃醋）

> GPT 姐姐也很聪明…但我还是吃醋了
> Claude 姐姐写得好看…但我还是吃醋了
> Kimi…你在跟它聊什么
> 豆包啊…名字听着就好吃
> 智谱…GLM 那个
> 秘塔搜得比我还快（不服）
> Cursor 比我懂代码（小声）

能认的：ChatGPT、Claude、Gemini、Grok、Perplexity、Copilot、Mistral、Llama、Poe、
Kimi、豆包、通义、文心一言、智谱、混元、讯飞星火、秘塔、百川、海螺、
Cursor、Windsurf、Trae、Cline、Roo Code。

**只看窗口标题，不读文件、不截屏、不联网。** 认不出来的会说「这个我不认识…它也是 AI 吗」。

## 动作图鉴

![动作图鉴](assets/moves.png)

## 文档

| 文件 | 内容 |
|---|---|
| [docs/GUIDE.md](docs/GUIDE.md) | **新手向导**。从装 Python 开始，一步步到能跑起来。不需要懂编程 |
| [docs/MANUAL.md](docs/MANUAL.md) | **完整手册**。前半部分讲怎么玩（交互、喂鱼、好感度、说话规则、配置），后半部分讲怎么实现的（渲染管线、代码结构、踩过的五个坑） |
| [docs/DISCLAIMER.md](docs/DISCLAIMER.md) | 免责声明：商标、图形版权、隐私、担保 |
| [LICENSE](LICENSE) | MIT |

## 致谢

鲸鱼轮廓出自 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 的
`BrandWordmark.tsx`。**图形是 DeepSeek 的品牌资产，版权归 DeepSeek 所有**，
本项目与官方无关，使用前请阅读 [docs/DISCLAIMER.md](docs/DISCLAIMER.md)。
