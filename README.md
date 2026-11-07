# 鲸鱼桌宠

一只住在屏幕角落的小鲸鱼。

轮廓不是贴的图——是从 DeepSeek 官方 logo 的矢量路径里逐点解析重绘的，
放大缩小都不糊，尾巴摆动时也是真的在变形。

![预览](assets/preview.png)

## 跑起来

```bash
pip install pillow
python whale_pet.py
```

Windows 上双击文件夹里的 `启动小鲸鱼.lnk` 也行。

只用 Pillow 一个依赖，不联网，不要账号。

## 它会做什么

- 呼吸浮动、甩尾巴、偶尔喷水、随机眨眼
- 眼睛跟着鼠标转，凑近了会害羞
- 点一下蹦起来，双击跳更高，按住能拖着走
- 30 秒没互动就趴下打瞌睡，开始说梦话
- **喂鱼**：右键叼起一条小鱼，鱼跟着光标跑，左键放下，它会游过去吃掉
- 记得认识多少天、被摸过几次、喂过多少条
- 切到全屏游戏时会自动躲开

## 动作图鉴

![动作图鉴](assets/moves.png)

## 文档

| 文件 | 内容 |
|---|---|
| [docs/MANUAL.md](docs/MANUAL.md) | 说明书。前半部分讲怎么玩（交互、喂鱼、好感度、说话规则、配置），后半部分讲怎么实现的（渲染管线、代码结构、踩过的五个坑） |
| [docs/DISCLAIMER.md](docs/DISCLAIMER.md) | 免责声明：商标、图形版权、隐私、担保 |
| [LICENSE](LICENSE) | MIT |

## 致谢

鲸鱼轮廓出自 [deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 的
`BrandWordmark.tsx`。**图形是 DeepSeek 的品牌资产，版权归 DeepSeek 所有**，
本项目与官方无关，使用前请阅读 [docs/DISCLAIMER.md](docs/DISCLAIMER.md)。
