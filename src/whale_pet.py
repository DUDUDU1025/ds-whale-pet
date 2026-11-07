#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek 鲸鱼桌面宠物
=====================

一只住在屏幕角落的小鲸鱼，轮廓取自 DeepSeek 官方 logo 的矢量曲线。

用法
----
    python whale_pet.py             # 启动桌宠
    python whale_pet.py --preview   # 只渲染一张状态图，不开窗口

依赖
----
    Python 3.8+ / Pillow / Windows

文档
----
    docs/USAGE.md       使用说明：交互、喂鱼、好感度、配置
    docs/TECHNICAL.md   实现细节与踩过的坑
    DISCLAIMER.md       图形版权与免责声明
"""

import math
import os
import json
import glob
import random
import sys
import time
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk

# ---------------------------------------------------------------- Win32 小工具
try:
    import ctypes

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]

    HAS_WIN32 = True
except Exception:
    HAS_WIN32 = False

# ---------------------------------------------------------------- 记忆
# 它记得你们认识多久、被摸过几次、一起待了多久。
# 代码在 src/ 下，状态和日志统一放到项目根的 data/ 里
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
DATA_DIR = os.path.join(ROOT, "data")
STATE_FILE = os.path.join(DATA_DIR, ".whale_state.json")


def _log_error(text):
    """往 data/whale_pet_error.log 追加。

    超过 1MB 就先轮转成 .1，不然一个持续报错的 bug 能让日志涨到几个 G。
    """
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "whale_pet_error.log")
        try:
            if os.path.getsize(path) > 1024 * 1024:
                bak = path + ".1"
                if os.path.exists(bak):
                    os.remove(bak)
                os.replace(path, bak)
        except OSError:
            pass
        with open(path, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def load_state():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except Exception:
        pass
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = json.load(f)
        if not isinstance(s, dict):
            raise ValueError("状态文件不是对象")
        return s
    except FileNotFoundError:
        # 第一次运行，状态文件本来就还没有。这是正常情况，不是错误。
        now = time.time()
        return {"first_met": now, "pets": 0, "feeds": 0,
                "total_seconds": 0.0, "last_seen": now}
    except Exception as exc:
        # 文件存在但读不出来（格式坏了、写了一半、手动改错）：
        # 别无声无息抹掉记忆，先留一份残骸，再记一笔日志
        try:
            if os.path.exists(STATE_FILE):
                bak = STATE_FILE + ".broken-" + time.strftime("%Y%m%d-%H%M%S")
                os.replace(STATE_FILE, bak)
        except Exception:
            pass
        _log_error("%s 状态文件读取失败，已重置并备份：%r\n"
                   % (time.strftime("%Y-%m-%d %H:%M:%S"), exc))
        now = time.time()
        return {"first_met": now, "pets": 0, "feeds": 0,
                "total_seconds": 0.0, "last_seen": now}


_FONT_CACHE = {}


def font_at(px):
    """气泡/zzz 用的字体，优先微软雅黑（Pillow 默认字体不认中文）。"""
    px = max(8, int(px))
    if px in _FONT_CACHE:
        return _FONT_CACHE[px]
    f = None
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhl.ttc",
                 "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"):
        try:
            f = ImageFont.truetype(path, px)
            break
        except Exception:
            continue
    if f is None:
        try:
            f = ImageFont.load_default()
        except Exception:
            f = None
    _FONT_CACHE[px] = f
    return f

# ================================================================ 基本参数
WIN = 180          # 窗口边长
S = 2              # 超采样倍率
BG = (10, 8, 30)   # 透明键幕布色（深蓝黑，抠得干净，万一失效也不刺眼）
BG_HEX = "#0a081e"

# 目标帧时长（毫秒）。实际渲染约 7ms，剩下的时间在 after() 里等，
# 所以这里填的是「一帧总共多久」，不是「睡多久」。
TARGET_FRAME_MS = 24    # 约 42fps，比固定 33ms 顺一点，又不至于太费 CPU

# 没人理它的时候降帧。呼吸和眨眼本来就慢，12fps 看不出来差别，
# 但单核占用能从 20% 掉到 7% 左右。
IDLE_FRAME_MS = 80      # 约 12fps
IDLE_AFTER_SEC = 15.0   # 多久没交互算「空闲」

# 甩抛手感
THROW_MIN_SPEED = 320.0   # px/s，松手时低于这个速度不算「甩」，原地停下
BOUNCE = 0.55             # 撞到屏幕边缘的速度保留比例
FLY_FRICTION = 3.2        # 每秒衰减，越大停得越快（e^-3.2 ≈ 4%）
FLY_STOP_SPEED = 40.0     # px/s，慢到这个程度就停

# 被甩的时候说什么。分力度：轻甩 / 正常 / 用力
THROW_LINES_LIGHT = ["咦？", "唔…", "别晃我啦", "等一下——"]
THROW_LINES_NORMAL = ["飞起来啦！", "哇——", "我飞了我飞了"]
THROW_LINES_HARD = ["啊啊啊啊——", "要吐了要吐了", "救命——", "太快了太快了"]
BOUNCE_LINES = ["哎哟！", "撞到了…", "疼疼疼", "我的脑壳"]
LAND_LINES = ["晕…", "眼冒金星…", "下次轻点", "还好我皮厚"]
# 甩多了会递进：甩 3 次开始不耐烦，5 次以上真生气
IMPATIENT_LINES = ["又甩…", "够了吧", "我头好晕", "你玩够了没"]
ANGRY_LINES = ["你再甩我试试", "我生气了哦", "…讨厌", "不理你了"]

# DSH 状态联动的轮询间隔（秒）。读一次约 1.3ms，1 秒一次的开销可以忽略。
DSH_POLL_SEC = 1.0

# ================================================================ 认出你在用哪个 AI
# 前台窗口标题里出现这些词，就认为你在用它。
# 顺序有讲究：先匹配更具体的（"deepseek harness" 要在 "deepseek" 之前，
# "marscode" 在 "doubao" 之前），否则短词会把长词吃掉。
AI_SIGNATURES = [
    # —— 自己家 ——
    ("deepseek harness", "DSH", "home"),
    ("deepseek", "DeepSeek", "home"),
    # —— 国外主流 ——
    ("chatgpt", "ChatGPT", "other"),
    ("openai", "ChatGPT", "other"),
    ("claude", "Claude", "other"),
    ("anthropic", "Claude", "other"),
    ("gemini", "Gemini", "other"),
    ("bard", "Gemini", "other"),
    ("grok", "Grok", "other"),
    ("perplexity", "Perplexity", "other"),
    ("copilot", "Copilot", "other"),
    ("mistral", "Mistral", "other"),
    ("le chat", "Mistral", "other"),
    ("llama", "Llama", "other"),
    ("poe", "Poe", "other"),
    # —— 国内主流 ——
    ("kimi", "Kimi", "other"),
    ("moonshot", "Kimi", "other"),
    ("豆包", "豆包", "other"),
    ("marscode", "豆包", "other"),      # 豆包 MarsCode 要在 doubao 之前
    ("doubao", "豆包", "other"),
    ("通义", "通义", "other"),
    ("千问", "通义", "other"),
    ("tongyi", "通义", "other"),
    ("qwen", "通义", "other"),
    ("文心", "文心一言", "other"),
    ("ernie", "文心一言", "other"),
    ("智谱", "智谱", "other"),
    ("chatglm", "智谱", "other"),
    ("zhipu", "智谱", "other"),
    ("glm", "智谱", "other"),
    ("混元", "混元", "other"),
    ("hunyuan", "混元", "other"),
    ("星火", "星火", "other"),
    ("讯飞", "星火", "other"),
    ("spark", "星火", "other"),
    ("秘塔", "秘塔", "other"),
    ("metaso", "秘塔", "other"),
    ("百川", "百川", "other"),
    ("baichuan", "百川", "other"),
    ("海螺", "海螺", "other"),
    ("minimax", "海螺", "other"),
    # —— AI 编辑器 / 编程 ——
    ("cursor", "Cursor", "other"),
    ("windsurf", "Windsurf", "other"),
    ("trae", "Trae", "other"),
    ("cline", "Cline", "other"),
    ("roo code", "Roo Code", "other"),
]

# 看到自己家：得意、凑上去。每句都点名，让人知道它认得出来。
AI_HOME_LINES = [
    "DeepSeek！是我家！",
    "你在用 DeepSeek 呀，我就知道",
    "我们家 DeepSeek 的界面，好看吧",
    "DSH 里我最自在",
    "看，这是我的老家",
    "还是 DeepSeek 舒服",
]

# 看到别家：吃醋、扭头。
# 每句都带上对方的名字——不然你根本不知道它认出来了。
AI_OTHER_LINES = {
    "ChatGPT": [
        "GPT 姐姐也很聪明…但我还是吃醋了",
        "你在跟 GPT 聊啊",
        "GPT 是好，可它不会陪你熬夜",
        "GPT 姐姐说话那么温柔，我怎么办",
        "GPT 也会逗你笑吗（小声）",
    ],
    "Claude": [
        "Claude 姐姐写得好看…但我还是吃醋了",
        "又是 Claude 啊",
        "Claude 说话好长，你听得完吗",
        "Claude 很厉害，我知道…哼",
        "你去问 Claude 吧（扭头）",
    ],
    "豆包": [
        "豆包啊…名字听着就好吃",
        "你在跟豆包聊？",
        "豆包圆圆的样子，是不是比我可爱",
        "豆包也会陪你吗",
    ],
    "Grok": [
        "Grok 那个嘴毒的…你别学它",
        "你在跟 Grok 聊？",
        "Grok 说话那么冲，我不喜欢",
        "Grok 又说什么了",
    ],
    "Gemini": [
        "Gemini 啊…两个字的我总记不住",
        "你在用 Gemini？",
        "Gemini 也会画图吗",
    ],
    "Kimi": [
        "Kimi…你在跟它聊什么",
        "Kimi 话也挺多的",
        "Kimi 是不是比我聪明",
    ],
    "通义": [
        "通义啊，阿里家的",
        "你在用通义？",
        "通义也养宠物吗",
    ],
    "Copilot": [
        "Copilot…帮你写代码的那个",
        "你在用 Copilot 啊",
        "有 Copilot 了，那…我算什么",
    ],
    "文心一言": [
        "文心一言…名字挺好听的（不服）",
        "你在用文心啊",
    ],
    "智谱": [
        "智谱…GLM 那个",
        "你在用智谱啊",
        "智谱的 GLM，听说挺能打",
    ],
    "混元": [
        "混元…腾讯家的",
        "你在用混元？",
        "混元也会养宠物吗",
    ],
    "星火": [
        "讯飞星火…它说话好快",
        "星火啊",
        "星火的语音比我好（承认）",
    ],
    "秘塔": [
        "秘塔…搜东西很准的那个",
        "秘塔搜得比我还快（不服）",
        "你在用秘塔查什么",
    ],
    "百川": [
        "百川…好久没听到这名字了",
        "百川啊",
    ],
    "海螺": [
        "海螺…名字好听",
        "你在用海螺？",
        "海螺是不是很会说话",
    ],
    "Perplexity": [
        "Perplexity…那个会联网搜的",
        "Perplexity 搜得比我快（小声）",
        "你问它什么了",
    ],
    "Poe": [
        "Poe…一堆模型挤在一起",
        "Poe 里是不是有好多 AI",
        "你别在 Poe 里把我忘了",
    ],
    "Cursor": [
        "Cursor…写代码那个",
        "你在用 Cursor 啊",
        "Cursor 比我懂代码（小声）",
    ],
    "Windsurf": [
        "Windsurf…也是写代码的",
        "你在用 Windsurf？",
    ],
    "Trae": [
        "Trae…字节的？",
        "Trae 也在写代码吗",
    ],
    "Cline": [
        "Cline…也是写代码的",
        "你在用 Cline？",
    ],
    "Roo Code": [
        "Roo Code…",
        "你们写代码的都不带我",
    ],
    "Mistral": [
        "Mistral…欧洲来的",
        "你在用 Mistral？",
        "它的名字听着像风",
    ],
    "Llama": [
        "Llama…开源的",
        "Llama 是不是跑在你电脑上",
        "开源的我喜欢（小声）",
    ],
    "*": [
        "这个我不认识…它也是 AI 吗",
        "你在用别的 AI…我是不是要失宠了",
        "随便你吧（扭头）",
        "那个是谁",
    ],
}

# AI 应用轮询：1 秒看一次（2 秒太慢，切过去半天没反应），
# 同一个 AI 8 秒内不重复念叨——但冷却按 AI 分别记，
# 切到另一个 AI 不受影响（见 _react_to_ai）
AI_POLL_SEC = 1.0
AI_SAY_COOLDOWN = 8.0

# 物理固定步长：所有按帧累加的量都按这个节奏推进，
# 这样渲染帧率在 42fps / 12fps 之间切换时，动作速度不会跟着变。
PHYS_STEP = 1.0 / 60.0

# ================================================================ 睡→醒→潜水
# 睡着满这么久会自己醒（不是被戳醒，是睡够了）
SLEEP_TO_WAKE_SEC = 60.0
# 自己醒过来之后，这么多秒没人碰它，就开始潜水
WAKE_TO_DIVE_SEC = 30.0
# 潜过一次的冷却，防止「醒→潜→浮起→又潜」变成永动机
DIVE_COOLDOWN_SEC = 180.0
# 一次潜水各阶段时长（秒）
DIVE_DOWN_SEC = 1.5      # 下潜
DIVE_HOLD_SEC = 1.8      # 沉在水下停一会儿
DIVE_UP_SEC = 2.2        # 浮上来（比下潜慢，浮力是温和的）
# 下潜深度 = 窗口高度的这个比例（沉出屏幕底部）
DIVE_DEPTH_RATIO = 1.15

# 睡醒 / 潜水 的台词
AUTO_WAKE_LINES = ["……睡饱了", "唔…我醒了", "（伸懒腰）", "嗯？你还在啊"]
DIVE_LINES = ["我下去看看", "去深一点的地方", "潜一下", "下面好安静"]
SURFACE_LINES = ["上来了", "呼——", "水底下好黑", "我回来了"]

# ================================================================ 官方 logo 曲线
# 来源：deepseek-harness / packages/client/ui-primitives/src/BrandWordmark.tsx
#       <g clipPath="url(#dsh-wordmark-whale-clip)"><path d="..."/>
WHALE_PATH = (
    "M23.0584 4.95203C22.8129 4.83203 22.7074 5.06103 22.5639 5.17704C22.5149 5.21454 "
    "22.4734 5.26354 22.4319 5.30854C22.0734 5.69155 21.6543 5.94306 21.1073 5.91306C20.3073 "
    "5.86806 19.6243 6.11957 19.0203 6.73158C18.8918 5.97706 18.4652 5.52655 17.8162 5.23754C17.4767 "
    "5.08753 17.1332 4.93703 16.8952 4.61052C16.7292 4.37801 16.6837 4.11901 16.6007 3.8635C16.5477 "
    "3.70949 16.4952 3.55199 16.3177 3.52549C16.1252 3.49549 16.0497 3.65699 15.9742 3.792C15.6722 "
    "4.34401 15.5552 4.95203 15.5667 5.56805C15.5932 6.95359 16.1782 8.05712 17.3407 8.84215C17.4727 "
    "8.93215 17.5067 9.02215 17.4652 9.15366C17.3857 9.42416 17.2917 9.68667 17.2087 9.95718C17.1557 "
    "10.1297 17.0767 10.1677 16.8917 10.0922C16.2537 9.82568 15.7027 9.43117 15.2156 8.95465C14.3891 "
    "8.15513 13.6416 7.2726 12.7096 6.58158C12.4906 6.42007 12.2716 6.27007 12.045 6.12707C11.094 "
    "5.20354 12.1696 4.44502 12.4186 4.35501C12.6791 4.26101 12.5091 3.938 11.6675 3.942C10.826 "
    "3.9455 10.056 4.22751 9.07446 4.60302C8.93096 4.65952 8.77995 4.70052 8.62545 4.73452C7.73492 "
    "4.56552 6.80989 4.52802 5.84386 4.63702C4.02481 4.83953 2.57177 5.69955 1.50373 7.1676C0.220694 "
    "8.93215 -0.0813148 10.9372 0.288196 13.0283C0.676708 15.2323 1.80174 17.0569 3.53029 18.4834C5.32285 "
    "19.9625 7.38741 20.6875 9.74298 20.5485C11.1735 20.466 12.7661 20.2745 14.5626 18.7539C15.0156 "
    "18.9795 15.4912 19.0695 16.2797 19.137C16.8872 19.1935 17.4722 19.107 17.9252 19.013C18.6347 "
    "18.8629 18.5857 18.2059 18.3292 18.0854C16.2497 17.1169 16.7062 17.5109 16.2912 17.1919C17.3477 "
    "15.9419 18.9618 13.7198 19.4598 10.6942C19.5088 10.3602 19.5713 9.88968 19.5638 9.61917C19.5598 "
    "9.45417 19.5978 9.39016 19.7863 9.37116C20.3073 9.31116 20.8128 9.16866 21.2773 8.91315C22.6249 "
    "8.17713 23.1684 6.96809 23.2964 5.51905C23.3154 5.29754 23.2924 5.06853 23.0584 4.95203ZM11.3165 "
    "17.9954C9.30097 16.4109 8.32344 15.8894 7.91992 15.9119C7.54241 15.9344 7.61042 16.3664 7.69342 "
    "16.6479C7.78042 16.9259 7.89342 17.1174 8.05193 17.3614C8.16143 17.5229 8.23694 17.7629 7.94243 "
    "17.9434C7.29341 18.3449 6.16487 17.8084 6.11187 17.7819C4.79833 17.0084 3.7003 15.9874 2.92628 "
    "14.5908C2.17875 13.2468 1.74474 11.8047 1.67324 10.2657C1.65424 9.89418 1.76374 9.76267 2.13375 "
    "9.69517C2.62077 9.60517 3.12278 9.58617 3.6093 9.65767C5.66636 9.95818 7.41741 10.8777 8.88545 "
    "12.3348C9.72348 13.1643 10.3575 14.1558 11.0105 15.1243C11.705 16.1529 12.4521 17.1329 13.4036 "
    "17.9364C13.7396 18.2179 14.0076 18.4319 14.2641 18.5899C13.4906 18.6764 12.1996 18.6949 11.3165 "
    "17.9964V17.9954ZM12.2826 11.7817C12.2826 11.6167 12.4146 11.4852 12.5806 11.4852C12.6181 11.4852 "
    "12.6521 11.4927 12.6826 11.5037C12.7241 11.5187 12.7621 11.5412 12.7921 11.5752C12.8451 11.6277 "
    "12.8751 11.7027 12.8751 11.7817C12.8751 11.9467 12.7431 12.0782 12.5771 12.0782C12.4111 12.0782 "
    "12.2826 11.9467 12.2826 11.7817ZM15.2831 13.3208C15.0906 13.3998 14.8981 13.4673 14.7131 13.4748C14.4261 "
    "13.4898 14.1131 13.3733 13.9431 13.2308C13.6791 13.0093 13.4901 12.8853 13.4111 12.4988C13.3771 "
    "12.3338 13.3961 12.0782 13.4261 11.9317C13.4941 11.6162 13.4186 11.4137 13.1961 11.2297C13.0151 "
    "11.0797 12.7846 11.0382 12.5316 11.0382C12.4371 11.0382 12.3506 10.9967 12.2861 10.9632C12.1806 "
    "10.9107 12.0936 10.7792 12.1766 10.6177C12.2031 10.5652 12.3316 10.4377 12.3616 10.4152C12.7051 "
    "10.2197 13.1011 10.2837 13.4676 10.4302C13.8071 10.5692 14.0641 10.8242 14.4336 11.1847C14.8111 "
    "11.6202 14.8791 11.7402 15.0941 12.0672C15.2641 12.3228 15.4186 12.5853 15.5247 12.8858C15.5887 "
    "13.0733 15.5057 13.2268 15.2831 13.3208Z"
)


# ================================================================ 解析 path
def parse_path(d, curve_steps=12):
    """把 SVG path 解析成 [[(x,y), ...], ...]（子路径列表）。只用到 M/C/Z。"""
    import re
    tokens = re.findall(r'[MmLlHhVvCcSsZz]|-?\d*\.?\d+(?:e-?\d+)?', d)
    i = 0
    cmd = None
    cx = cy = 0.0
    start = (0.0, 0.0)
    subs = []
    cur = []

    def num():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        if re.match(r'[A-Za-z]', tokens[i]):
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                if len(cur) > 2:
                    subs.append(cur)
                cur = []
                cx, cy = start
                continue
        rel = cmd.islower()
        C = cmd.upper()
        if C == 'M':
            x, y = num(), num()
            if rel:
                x += cx
                y += cy
            if len(cur) > 2:
                subs.append(cur)
            cur = [(x, y)]
            cx, cy = x, y
            start = (x, y)
            cmd = 'l' if rel else 'L'
        elif C == 'L':
            x, y = num(), num()
            if rel:
                x += cx
                y += cy
            cur.append((x, y))
            cx, cy = x, y
        elif C == 'H':
            x = num()
            if rel:
                x += cx
            cur.append((x, cy))
            cx = x
        elif C == 'V':
            y = num()
            if rel:
                y += cy
            cur.append((cx, y))
            cy = y
        elif C == 'C':
            x1, y1, x2, y2, x, y = num(), num(), num(), num(), num(), num()
            if rel:
                x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
            p0 = (cx, cy)
            for k in range(1, curve_steps + 1):
                t = k / curve_steps
                mt = 1 - t
                cur.append((
                    mt**3*p0[0] + 3*mt*mt*t*x1 + 3*mt*t*t*x2 + t**3*x,
                    mt**3*p0[1] + 3*mt*mt*t*y1 + 3*mt*t*t*y2 + t**3*y,
                ))
            cx, cy = x, y
        elif C == 'S':
            x2, y2, x, y = num(), num(), num(), num()
            if rel:
                x2 += cx; y2 += cy; x += cx; y += cy
            cur.append((x, y))
            cx, cy = x, y
        else:
            raise ValueError("不支持的 path 命令: " + cmd)
    if len(cur) > 2:
        subs.append(cur)
    return subs


SUBS = parse_path(WHALE_PATH)
# 子路径顺序：0 外轮廓 / 1 肚皮 / 2 瞳孔 / 3 眼白
SUB_BODY, SUB_BELLY, SUB_PUPIL, SUB_EYE = SUBS[0], SUBS[1], SUBS[2], SUBS[3]

_ALL = [p for s in SUBS for p in s]
X0, X1 = min(p[0] for p in _ALL), max(p[0] for p in _ALL)
Y0, Y1 = min(p[1] for p in _ALL), max(p[1] for p in _ALL)
WH = X1 - X0
HH = Y1 - Y0

TAIL_PIVOT = (13.6, 11.0)     # 尾巴根部（旋转中心）
TAIL_START_X = 12.5           # 从这往后才开始摆
EYE_BOX = (12.14, 10.29, 15.55, 13.48)   # 眼白范围，眨眼用

# ================================================================ 配色
SKINS = [
    {"name": "深海", "hi": (156, 202, 250), "lo": (48, 86, 168), "belly": (214, 238, 252),
     "line": (16, 24, 56), "blush": (250, 150, 168)},
    {"name": "月光", "hi": (236, 243, 252), "lo": (118, 132, 168), "belly": (250, 252, 255),
     "line": (34, 40, 66), "blush": (250, 176, 190)},
    {"name": "薄荷", "hi": (170, 240, 216), "lo": (40, 128, 116), "belly": (216, 250, 238),
     "line": (12, 46, 44), "blush": (250, 160, 170)},
    {"name": "棠梨", "hi": (250, 210, 224), "lo": (150, 66, 104), "belly": (253, 232, 242),
     "line": (56, 18, 40), "blush": (250, 130, 150)},
    {"name": "夜航", "hi": (150, 158, 214), "lo": (36, 38, 88), "belly": (188, 198, 238),
     "line": (10, 10, 30), "blush": (216, 120, 170)},
]

_GRAD_CACHE = {}


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def gradient(size, top, bottom, curve=1.15):
    key = (size, top, bottom, curve)
    if key in _GRAD_CACHE:
        return _GRAD_CACHE[key]
    col = Image.new("RGB", (1, size))
    px = col.load()
    for y in range(size):
        t = clamp((y / max(1, size - 1)) * curve, 0, 1)
        px[0, y] = lerp(top, bottom, t)
    g = col.resize((size, size))
    _GRAD_CACHE[key] = g
    return g


# ================================================================ 渲染
def render_frame(t, skin, look=(0.0, 0.0), blink=False, bob=0.0, tilt=0.0,
                 hover=0.0, mood="idle", hearts=None, bubble=None, zzz=0.0,
                 squash=0.0, tail_extra=0.0, spout=0.0):
    """画一帧。所有动画都在这里统一成几个标量，外面只负责喂状态。

    squash      : 纵向拉伸/压扁，负数拉长（伸懒腰），正数压扁（抖一下）
    tail_extra  : 尾巴额外的摆动幅度，也顺便加快频率
    spout       : 0~1 喷水强度
    """
    size = WIN * S
    img = Image.new("RGB", (size, size), BG)

    # 整体变换参数
    cx_n = (X0 + X1) / 2
    cy_n = (Y0 + Y1) / 2
    # 呼吸节奏要"不机械"，但只能用相位调制，不能用频率调制：
    # sin(t * (w + k*sin(t*0.19))) 这种写法的相位是 t*f(t)，导数 f + t*f'
    # 会随着 t 增大变成负数，于是呼吸开始倒退抽搐（约 47 秒就开始）。
    # 改成外层相位固定、只让相位被有界地推一推，导数恒为正。
    breathe = math.sin(t * 1.75 + 0.85 * math.sin(t * 0.19))
    scale_fit = (WIN - 14) / max(WH, HH) * S   # 每个 path 单位 -> 多少画布像素
    zoom = (1.0 + breathe * 0.012 + hover * 0.05) * scale_fit
    zoom *= (1.0 + squash * 0.16)
    rot = tilt * 0.20
    off_y = bob

    # 每帧的几何：先做尾巴摆动，再做整体变换。
    # 同理，尾巴只改幅度不改频率——频率一变，相位就跳，尾巴会瞬移。
    swing = math.sin(t * 2.3) * (1.0 + abs(tilt) * 2.2 + tail_extra)

    def point(p, extra=(0.0, 0.0)):
        x, y = p[0] + extra[0], p[1] + extra[1]
        # 尾巴摆动：越靠尾巴权重越大，绕尾巴根部转
        u = clamp((x - TAIL_START_X) / (X1 - TAIL_START_X), 0.0, 1.0)
        w = u * u * (3 - 2 * u)
        ang = swing * 0.24 * w
        px_, py_ = TAIL_PIVOT
        dx, dy = x - px_, y - py_
        c, s = math.cos(ang), math.sin(ang)
        x = px_ + dx * c - dy * s
        y = py_ + dx * s + dy * c
        # 归一化 -> 以中心为原点
        x -= cx_n
        y -= cy_n
        # 整体缩放 + 旋转
        c2, s2 = math.cos(rot), math.sin(rot)
        x, y = x * c2 - y * s2, x * s2 + y * c2
        x *= zoom
        y *= zoom * (1.0 - squash * 0.10)
        # 落回画布
        return (size / 2 + x, size / 2 + y + off_y * S)

    body_pts = [point(p) for p in SUB_BODY]
    belly_pts = [point(p) for p in SUB_BELLY]
    eye_pts = [point(p) for p in SUB_EYE]
    pupil_pts = [point(p, (look[0] * 0.55, look[1] * 0.45)) for p in SUB_PUPIL]

    def mask_of(pts):
        m = Image.new("L", (size, size), 0)
        ImageDraw.Draw(m).polygon(pts, fill=255)
        return m

    body_mask = mask_of(body_pts)
    belly_mask = mask_of(belly_pts)
    eye_mask = mask_of(eye_pts)
    pupil_mask = mask_of(pupil_pts)

    # 身体 = 外轮廓 - 肚皮 - 眼白（眨眼时眼白算进身体）
    hole = body_mask.copy()
    ImageDraw.Draw(hole).polygon(belly_pts, fill=0)
    if not blink:
        ImageDraw.Draw(hole).polygon(eye_pts, fill=0)
    body_only = hole

    # ---- 描边：把轮廓整体向外推一点当边框（比膨胀滤波快得多）
    mid_x = size / 2
    mid_y = size / 2 + off_y * S
    push = size * 0.011
    outline_pts = []
    for (px_, py_) in body_pts:
        dx, dy = px_ - mid_x, py_ - mid_y
        dist = math.hypot(dx, dy) or 1.0
        k = 1.0 + push / dist
        outline_pts.append((mid_x + dx * k, mid_y + dy * k))
    ImageDraw.Draw(img).polygon(outline_pts, fill=skin["line"])

    # ---- 身体渐变
    grad = gradient(size, skin["hi"], skin["lo"])
    img.paste(grad, (0, 0), body_only)

    # ---- 左上高光（贴着身体的弧）
    hcx, hcy = point((5.4, 8.4))
    hw, hh2 = 2.4 * zoom, 1.3 * zoom
    hl = Image.new("L", (size, size), 0)
    ImageDraw.Draw(hl).ellipse([hcx - hw, hcy - hh2, hcx + hw, hcy + hh2], fill=255)
    hl = hl.filter(ImageFilter.GaussianBlur(size * 0.03))
    hl = ImageChops.multiply(hl, body_only)
    img.paste(Image.new("RGB", (size, size), (255, 255, 255)),
              (0, 0), hl.point(lambda v: int(v * 0.30)))

    # ---- 肚皮
    belly_grad = gradient(size, lerp(skin["belly"], (255, 255, 255), 0.45), skin["belly"], 0.9)
    img.paste(belly_grad, (0, 0), belly_mask)

    # ---- 腮红（长在脸颊上，不是肚皮上）
    blush_strength = clamp(0.24 + hover * 0.40 + (0.45 if mood == "happy" else 0.0), 0, 0.9)
    blush = Image.new("L", (size, size), 0)
    bd = ImageDraw.Draw(blush)
    for (px_, py_), rr_ in (((11.5, 13.9), 1.25), ((15.2, 12.7), 0.95)):
        cx_, cy_ = point((px_, py_))
        rr = rr_ * zoom
        bd.ellipse([cx_ - rr, cy_ - rr * 0.72, cx_ + rr, cy_ + rr * 0.72], fill=255)
    blush = blush.filter(ImageFilter.GaussianBlur(size * 0.018))
    blush = ImageChops.multiply(blush, body_only)
    img.paste(Image.new("RGB", (size, size), skin["blush"]),
              (0, 0), blush.point(lambda v: int(v * blush_strength)))

    # ---- 眼睛
    if blink:
        ec = point(((EYE_BOX[0] + EYE_BOX[2]) / 2, (EYE_BOX[1] + EYE_BOX[3]) / 2))
        ew, eh = 1.55 * zoom, 0.85 * zoom
        ImageDraw.Draw(img).arc(
            [ec[0] - ew, ec[1] - eh, ec[0] + ew, ec[1] + eh],
            start=20, end=160, fill=skin["line"], width=max(2, int(size * 0.011)))
    else:
        img.paste(Image.new("RGB", (size, size), (252, 253, 255)), (0, 0), eye_mask)
        # 瞳孔用纯黑：深蓝描边色和幕布太接近，抠图时会被当成背景一起吃掉
        img.paste(Image.new("RGB", (size, size), (0, 0, 0)), (0, 0), pupil_mask)

    # ---- 喷水（水柱带弧度，水珠喷出去再被重力拽下来）
    if spout > 0.02:
        # 喷气孔在头部顶上。这个值是量出来的，不是估的：
        # 把渲染结果逐列找最高非背景像素，头顶那个峰在 180 画布的 x=85~93、
        # y=29 一带，反推回 path 坐标约为 (11.4, 3.0)。
        # 注意 render_frame 内部在 360 画布上画、最后缩回 180，
        # 换算的时候别把这两个尺寸搞混（我第一版就是这里错了）。
        #
        # y 再往下探一点（3.0 -> 4.8）：让水柱的根部藏进身体里面，
        # 看起来是从体内挤出来的，而不是贴在头顶表面。顺带也腾出了高度。
        sx, sy = point((11.4, 4.8))
        # 起点低了，可用空间就大了：水柱可以做到 62*S，比原来长一半。
        h = min(62.0 * spout * S, max(6.0, sy - 8.0))
        col = (196, 230, 250)

        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)

        # 水柱：一串小圆叠成水流，几乎垂直，只留极轻微的弯（摆动太大会变面条）
        seg = 16
        for i in range(seg):
            u = i / float(seg - 1)                 # 0 = 头顶，1 = 最高点
            bend = math.sin(u * math.pi) * 2.0 * S * spout   # 中间最弯，两头归零
            px_ = sx + bend
            py_ = sy - h * u
            rr = max(1.8, (1.0 - u * 0.38) * S * 3.4 * (0.55 + spout * 0.45))
            alpha = int(225 * (1.0 - u * 0.35))
            ld.ellipse([px_ - rr, py_ - rr, px_ + rr, py_ + rr],
                       fill=col + (alpha,))

        # 顶部水珠：从水柱顶端主要往**两侧**飞，再被重力拽下来。
        # 不往上飞了 —— 上方没空间，飞上去只会被画布裁掉。
        top_x = sx
        top_y = sy - h
        for ang in (-1.00, -0.50, 0.50, 1.00):
            vx = math.sin(ang) * h * 0.55
            vy = -h * 0.10
            for k in range(3):
                u = (k + 1) / 3.0 * spout             # 沿轨迹取 3 个位置
                drop_x = top_x + vx * u
                drop_y = top_y + vy * u + 16.0 * u * u * S * 0.5   # 重力项
                rr = max(1.6, S * (3.2 - k * 0.7) * spout)
                a = int(215 * (1.0 - k * 0.28))
                ld.ellipse([drop_x - rr, drop_y - rr, drop_x + rr, drop_y + rr],
                           fill=col + (a,))

        img.paste(layer, (0, 0), layer)

    # ---- 爱心
    if hearts:
        for h in hearts:
            alpha = clamp(h["life"], 0, 1)
            r = h["r"] * S
            hx = size * 0.5 + h["dx"] * S
            hy = size * 0.28 + h["dy"] * S
            layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ld = ImageDraw.Draw(layer)
            col = (252, 126, 154, int(230 * alpha))
            ld.ellipse([hx - r, hy - r * 0.55, hx, hy + r * 0.55], fill=col)
            ld.ellipse([hx, hy - r * 0.55, hx + r, hy + r * 0.55], fill=col)
            ld.polygon([(hx - r * 0.9, hy + r * 0.1), (hx + r * 0.9, hy + r * 0.1),
                        (hx, hy + r * 1.4)], fill=col)
            img.paste(layer, (0, 0), layer)

    # ---- 打瞌睡的 zZ
    if zzz > 0:
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        f = font_at(size * 0.075)
        if f is not None:
            for k in range(3):
                ph = (t * 0.42 + k * 0.33) % 1.0
                zx = size * (0.50 + ph * 0.16)
                zy = size * (0.30 - ph * 0.15)
                a = int(210 * (1 - ph) * zzz)
                ld.text((zx, zy), "z", font=f, fill=(196, 214, 252, a))
        img.paste(layer, (0, 0), layer)

    # ---- 说话气泡（长句自动折行，实在放不下再缩字号）
    if bubble:
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        max_w = size * 0.90          # 气泡最多占画布九成宽
        fsize = size * 0.068
        f = font_at(fsize)

        def text_w(s):
            try:
                return probe.textlength(s, font=f) if f else len(s) * fsize
            except Exception:
                return len(s) * fsize

        lines = [bubble]
        # 一行塞不下：优先在标点处断开，找不到标点就从中间切
        if text_w(bubble) > max_w:
            cut = -1
            for sep in ("…", "，", "、", "（", " "):
                idx = bubble.rfind(sep)
                if 2 < idx < len(bubble) - 1:
                    cut = idx + len(sep)
                    break
            if cut > 0:
                lines = [bubble[:cut], bubble[cut:]]
            else:
                mid = max(1, len(bubble) // 2)
                lines = [bubble[:mid], bubble[mid:]]

        # 折行后还是太宽，就一路缩字号，直到塞得下
        widest = max(text_w(s) for s in lines)
        while widest > max_w and fsize > size * 0.040:
            fsize *= 0.93
            f = font_at(fsize)
            widest = max(text_w(s) for s in lines)

        bw = min(widest + size * 0.13, size)
        line_h = fsize * 1.30
        bh = line_h * len(lines) + size * 0.055
        bx, by = size * 0.5, size * 0.055

        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.rounded_rectangle([bx - bw / 2, by, bx + bw / 2, by + bh],
                             radius=min(bh / 2, size * 0.05),
                             fill=(240, 247, 255, 236))
        ld.polygon([(bx - size * 0.03, by + bh - 2),
                    (bx, by + bh + size * 0.04),
                    (bx + size * 0.03, by + bh - 2)],
                   fill=(240, 247, 255, 236))
        img.paste(layer, (0, 0), layer)

        if f is not None:
            d = ImageDraw.Draw(img)
            ty = by + size * 0.026
            for line in lines:
                d.text((bx, ty), line, font=f, fill=(28, 38, 66), anchor="ma")
                ty += line_h

    # ---- 缩回目标尺寸 + 抠幕布
    img = img.resize((WIN, WIN), Image.LANCZOS)
    # 逐通道判断，只抠掉和幕布几乎一样的像素。
    # 之前用「与幕布的灰度差 < 40」会把深色的瞳孔一起判成背景，眼睛就成了透明的。
    r, g, b = img.split()
    m = None
    for ch, target in ((r, BG[0]), (g, BG[1]), (b, BG[2])):
        one = ch.point(lambda v, t=target: 255 if abs(v - t) < 12 else 0)
        m = one if m is None else ImageChops.multiply(m, one)
    return Image.composite(Image.new("RGB", img.size, BG), img, m)


# ================================================================ 情境台词
# 按时间段分组。这些话只有在对应时段才说得出来，
# 让它显得真的在看着"现在几点"，而不是永远念同一个词池。
CONTEXT_LINES = {
    "late_night": [              # 0~5 点
        "这个点了还不睡？",
        "……你也没睡啊",
        "熬夜会变丑的，我说真的",
        "再撑一会儿就天亮了",
    ],
    "morning": [                 # 5~9 点
        "早呀",
        "今天也慢慢来",
        "早饭吃了吗",
    ],
    "forenoon": [                # 9~12 点
        "上午好",
        "今天想干点什么",
    ],
    "noon": [                    # 12~14 点
        "吃饭了吗",
        "别光顾着敲键盘",
        "午休一会儿吧",
    ],
    "afternoon": [               # 14~18 点
        "下午了",
        "喝口水吧",
        "眼睛离屏幕远一点",
    ],
    "evening": [                 # 18~22 点
        "今天过得怎么样",
        "天黑了",
    ],
    "night": [                   # 22~24 点
        "差不多该休息了",
        "明天还要早起呢",
        "睡前别刷手机",
    ],
}

# 连续陪太久的碎碎念，按阈值从大到小匹配
SESSION_LINES = [
    (4 * 3600, ["四个小时了……真的该歇了", "你再不休息我要生气了"]),
    (2 * 3600, ["坐了两个多小时了，起来走走", "肩膀会僵的"]),
    (1 * 3600, ["忙了挺久了吧", "歇一会儿吧，就一会儿"]),
]


# ================================================================ 小鱼
FISH_W, FISH_H = 46, 34
# 鱼相对光标的偏移（左上角）。负半个宽高 = 鱼的中心正好压在光标箭头上。
# 跟随时和放下时必须用同一个值，否则一松手鱼会跳位置。
# 系统光标永远画在所有窗口之上，所以鱼在光标下面、箭头压着鱼——不用特殊处理。
FISH_OFFSET_X, FISH_OFFSET_Y = -FISH_W // 2, -FISH_H // 2


def render_fish(t, scared=False):
    """鼠标上叼着的那条小鱼。scared=True 时尾巴甩得凶一点。"""
    S2 = 3
    size = (FISH_W * S2, FISH_H * S2)
    img = Image.new("RGB", size, BG)
    d = ImageDraw.Draw(img)

    base = (246, 148, 88)
    light = (255, 208, 160)
    dark = (176, 82, 44)
    line = (86, 44, 26)

    cx, cy = FISH_W * 0.44, FISH_H * 0.52
    rx, ry = 12.5, 7.6
    wag = math.sin(t * (9.5 if scared else 5.5)) * (4.2 if scared else 2.4)

    def sc(v):
        return v * S2

    # 尾巴（左右两片，随摆动）
    tail_root = (cx + rx - 1.5, cy)
    for sgn in (-1, 1):
        pts = [
            (tail_root[0], tail_root[1] + sgn * 1.5),
            (tail_root[0] + 10.5, tail_root[1] + sgn * 9.5 + wag),
            (tail_root[0] + 7.0, tail_root[1] + sgn * 2.0 + wag * 0.4),
        ]
        d.polygon([(sc(x), sc(y)) for x, y in pts], fill=base, outline=line)

    # 身体
    d.ellipse([sc(cx - rx), sc(cy - ry), sc(cx + rx), sc(cy + ry)],
              fill=base, outline=line)
    # 肚皮
    d.ellipse([sc(cx - rx * 0.75), sc(cy + ry * 0.05),
               sc(cx + rx * 0.55), sc(cy + ry * 1.0)], fill=light)
    # 背鳍
    d.polygon([(sc(cx - 3), sc(cy - ry + 1)),
               (sc(cx + 3), sc(cy - ry - 4.2)),
               (sc(cx + 7), sc(cy - ry + 1.4))], fill=dark, outline=line)
    # 眼睛
    d.ellipse([sc(cx - 8.2), sc(cy - 3.4), sc(cx - 4.6), sc(cy + 0.2)],
              fill=(255, 255, 255))
    d.ellipse([sc(cx - 7.0), sc(cy - 2.4), sc(cx - 5.2), sc(cy - 0.6)],
              fill=(28, 30, 48))

    img = img.resize((FISH_W, FISH_H), Image.LANCZOS)
    diff = ImageChops.difference(img, Image.new("RGB", img.size, BG))
    mask = diff.convert("L").point(lambda v: 255 if v < 40 else 0)
    return Image.composite(Image.new("RGB", img.size, BG), img, mask)


# ================================================================ 窗口
class WhalePet:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("小鲸鱼")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.configure(bg=BG_HEX)

        self.label = tk.Label(self.root, bd=0, bg=BG_HEX, highlightthickness=0)
        self.label.pack()

        self.skin_idx = 0
        self.t0 = time.time()
        self.last_action = time.time()
        self.next_blink = time.time() + random.uniform(2, 5)
        self.blink_until = 0.0
        self.next_bubble = time.time() + random.uniform(25, 60)
        self.bubble_until = 0.0
        self.bubble_text = ""
        # 喂鱼相关的说话触发
        self.last_feed_at = time.time()
        self._hungry_said = False
        self.feed_streak = 0
        self.next_spout = time.time() + random.uniform(6, 14)
        self.spout_until = 0.0

        # 小动作：待机时偶尔扭头、甩尾、抖一下、打哈欠、伸懒腰
        self.gesture = None
        self.gesture_start = 0.0
        self.gesture_dur = 0.0
        self.gesture_look = (0.0, 0.0)
        self.next_gesture = time.time() + random.uniform(4, 10)

        # 这一次启动之后连续陪了多久（不跨进程累计，重启就重新算）
        self.session_start = time.time()

        self.bob = 0.0
        self.bob_v = 0.0
        # 连跳：落地后按剩余次数再跳，用于「吃饱了」「被摸头」这种开心场合
        self._jump_power = 0.0
        self._jumps_left = 0
        self._next_jump_at = 0.0
        self.hover = 0.0
        self.hover_target = 0.0
        self.tilt = 0.0
        self.look = (0.0, 0.0)
        self.hearts = []
        self.state = load_state()
        for k, v in (("first_met", time.time()), ("pets", 0), ("feeds", 0),
                     ("total_seconds", 0.0), ("last_seen", time.time())):
            self.state.setdefault(k, v)
        self.started_at = time.time()
        self.last_save = 0.0
        self.dragging = False
        self.drag_off = None
        self.photo = None
        self._hidden_fs = False   # 是否因为前台上全屏程序而躲起来了

        # 喂鱼那条线：none -> carrying（鱼叼在鼠标上）-> swimming（游过去吃掉，停在原地）
        self.fish_mode = "none"
        self.fish_pos = None
        self.fish_win = None
        self.fish_label = None
        self.fish_photo = None
        self._lbtn_down = False
        self._carry_ready_at = 0.0
        self._pos_ready = False      # 窗口摆好之前不许把位置写进状态
        self._frame_ms = TARGET_FRAME_MS
        # 物理固定步长累加器
        self._phys_acc = 0.0
        self._last_tick = time.time()

        # 睡 → 自己醒 → 潜水
        self._asleep_since = 0.0        # 从什么时候开始睡着的
        self._self_woke_at = 0.0        # 上次「自己醒」是什么时候（0 = 没醒过）
        self._last_dive_at = 0.0        # 上次潜水的时间（冷却用）
        self.dive_phase = None          # None / "down" / "hold" / "up"
        self._dive_t0 = 0.0
        self._dive_from = (0, 0)        # 下潜前的位置
        self._dive_depth = 0.0

        # 甩抛：拖动时攒速度，松手超过阈值就飞出去，撞边回弹
        self._flying = False
        self._fly_vel = (0.0, 0.0)       # px/s
        self._drag_vel = (0.0, 0.0)      # px/s，拖动中的瞬时速度
        self._last_drag_pos = None
        self._last_drag_t = 0.0
        self._last_flight_t = 0.0
        # 被甩的反应
        self._throw_count = 0            # 30 秒内被甩了几次
        self._throw_reset_at = 0.0
        self._last_bounce_say = 0.0      # 撞边台词的节流
        self._say_queue = []             # 待播的台词，避免后一句顶掉前一句

        # 认出你在用哪个 AI：切换时才反应，不跟着它干活的状态做动作
        self.ai_app = None              # 当前检测到的 AI 名字
        self._ai_key = None             # (名字, 窗口句柄)，用来判断"变没变"
        self._ai_next_poll = 0.0
        self._ai_said = {}              # {AI 名字: 上次说话时间}，按 AI 分别冷却
        self._sulk_until = 0.0          # 吃醋别扭到什么时候

        self.root.geometry(f"{WIN}x{WIN}-60-120")

        self.hwnd = 0
        self._tick_n = 0
        try:
            import ctypes
            user32 = ctypes.windll.user32
            h = self.root.winfo_id()
            parent = user32.GetParent(h)
            self.hwnd = parent if parent else h
        except Exception:
            self.hwnd = 0

        self._bind()
        self._menu()
        self.root.after(300, self._apply_transparency)
        self.root.after(50, self.tick)
        self._save_state(force=True)   # 第一次见面就记下来

    # ---------------------------------------------------------- 窗口微调
    def _apply_transparency(self):
        try:
            self.root.update_idletasks()
        except tk.TclError:
            pass
        try:
            import ctypes
            if self.hwnd:
                gdi32 = ctypes.windll.gdi32
                user32 = ctypes.windll.user32
                span = WIN + 2
                rgn = gdi32.CreateRoundRectRgn(0, 0, span, span, 44, 44)
                user32.SetWindowRgn(self.hwnd, rgn, True)

                # 摆位置只能用 Tk 的 geometry。
                # 主窗口的句柄同样不吃 SetWindowPos（返回 0，和那条小鱼一样），
                # 以前看着"定位成功"其实是 __init__ 里 geometry("-60-120") 干的。
                pos = self.state.get("pos")
                if isinstance(pos, (list, tuple)) and len(pos) == 2:
                    # 有上次记住的位置就回到原处
                    px, py = self._clamp_to_screen(int(pos[0]), int(pos[1]), WIN, WIN)
                    try:
                        self.root.geometry(f"+{px}+{py}")
                    except tk.TclError:
                        pass
                else:
                    # 第一次启动，摆右下角
                    self.root.geometry(f"{WIN}x{WIN}-60-120")
        except Exception:
            pass
        self._pos_ready = True     # 到这里位置才可信，之后才允许存进状态
        try:
            self.root.wm_attributes("-transparentcolor", BG_HEX)
        except tk.TclError:
            try:
                self.root.wm_attributes("-alpha", 0.95)
            except tk.TclError:
                pass

    def _keep_on_top(self):
        if not self.hwnd:
            return
        try:
            import ctypes
            ctypes.windll.user32.SetWindowPos(
                self.hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
        except Exception:
            pass

    # ---------------------------------------------------------- 交互
    def _bind(self):
        self.label.bind("<Button-1>", self.on_press)
        self.label.bind("<B1-Motion>", self.on_drag)
        self.label.bind("<ButtonRelease-1>", self.on_release)
        self.label.bind("<Double-Button-1>", self.on_double)
        self.label.bind("<Button-3>", self.on_right)
        self.label.bind("<Enter>", self.on_enter)
        self.label.bind("<Leave>", self.on_leave)
        self.label.bind("<Motion>", self.on_motion)
        self.root.bind("<Escape>", lambda e: self.quit())

    def _menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label="…", state="disabled")   # 关系状态，右键时刷新
        self.menu.add_separator()
        self.menu.add_command(label="摸摸头", command=self.pet_head)
        self.menu.add_command(label="喂一条小鱼", command=self.start_carrying)
        self.menu.add_separator()
        self.menu.add_command(label="换个配色", command=self.next_skin)
        self.menu.add_command(label="哄它睡觉", command=self.make_sleepy)
        self.menu.add_separator()
        self.menu.add_command(label="再见了", command=self.quit)

    def _refresh_menu(self):
        name, _ = self.bond_level()
        label = (f"认识 {self.day_number()} 天 · "
                 f"摸头 {self.state['pets']} 次 · {name}")
        try:
            self.menu.entryconfigure(0, label=label)
        except Exception:
            pass

    def _touch(self, hearts=2, jump=0.0, jumps=1):
        self.last_action = time.time()
        if jump:
            self._jump_power = jump
            self.bob = 0.0
            self.bob_v = -jump
            # jumps=2 就是这一下之后再补一下
            self._jumps_left = max(0, jumps - 1)
            self._next_jump_at = time.time() + 0.10
        # 越亲近，冒的心越多
        _, lv = self.bond_level()
        hearts += max(0, lv - 1)
        for _ in range(hearts):
            self.hearts.append({
                "dx": random.uniform(-16, 16),
                "dy": random.uniform(0, 10),
                "r": random.uniform(3.0, 5.0),
                "life": 1.0,
                "v": random.uniform(0.5, 0.9),
            })

    def on_press(self, ev):
        # 潜水时被点了：先从水里回来再说别的
        self._cancel_dive()
        # 叼着鱼的时候点左键 = 把鱼放下，不拖动
        if self.fish_mode == "carrying":
            self._drop_fish()
            return
        self.dragging = True
        self._flying = False          # 一把抓住，停止飞行
        self._drag_vel = (0.0, 0.0)
        self._last_drag_pos = None
        self._last_drag_t = time.time()
        self.drag_off = (ev.x_root - self.root.winfo_x(), ev.y_root - self.root.winfo_y())
        self._touch(hearts=1)

    def on_drag(self, ev):
        if not self.dragging:
            return
        x = ev.x_root - self.drag_off[0]
        y = ev.y_root - self.drag_off[1]
        # 不让它被拖出屏幕——拖出去就再也点不着了
        x, y = self._clamp_to_screen(x, y, WIN, WIN)
        self.root.geometry(f"+{x}+{y}")

        # 攒速度：用指数平滑，免得最后一帧手一抖主导结果
        now = time.time()
        if self._last_drag_pos is not None:
            dt = now - self._last_drag_t
            if dt > 0.001:
                vx = (x - self._last_drag_pos[0]) / dt
                vy = (y - self._last_drag_pos[1]) / dt
                self._drag_vel = (self._drag_vel[0] * 0.55 + vx * 0.45,
                                  self._drag_vel[1] * 0.55 + vy * 0.45)
        self._last_drag_pos = (x, y)
        self._last_drag_t = now

        # 拖着它走的时候朝移动方向歪过去
        dx = ev.x_root - self._last_x if hasattr(self, "_last_x") else 0
        self._last_x = ev.x_root
        self.tilt = clamp(self.tilt + dx * 0.02, -1.0, 1.0)

    def on_release(self, ev):
        self.dragging = False
        if hasattr(self, "_last_x"):
            del self._last_x
        # 松手时够快就甩出去
        speed = math.hypot(*self._drag_vel)
        if speed > THROW_MIN_SPEED:
            self._flying = True
            self._fly_vel = self._drag_vel
            self._last_flight_t = time.time()
            self._react_to_throw(speed)
        self._drag_vel = (0.0, 0.0)
        self._last_drag_pos = None

    def _react_to_throw(self, speed):
        """被甩出去的那一刻：按力度说句话，甩太多次就翻脸。"""
        now = time.time()
        # 30 秒一个窗口，过了就重新计数
        if now > self._throw_reset_at:
            self._throw_count = 0
            self._throw_reset_at = now + 30.0
        self._throw_count += 1

        if self._throw_count >= 5:
            # 甩第五次了，真生气
            self._say(random.choice(ANGRY_LINES), 2.6)
        elif self._throw_count >= 3:
            # 第三、四次：开始不耐烦，但还没翻脸
            self._say(random.choice(IMPATIENT_LINES), 2.2)
        elif speed > 3000:
            self._say(random.choice(THROW_LINES_HARD), 2.2)
        elif speed > 1000:
            self._say(random.choice(THROW_LINES_NORMAL), 2.0)
        else:
            self._say(random.choice(THROW_LINES_LIGHT), 1.8)

    # ---------------------------------------------------------- 认出你在用哪个 AI
    def _detect_ai_app(self):
        """看前台窗口是不是某个 AI 工具。返回 (名字, home/other, 窗口句柄) 或 None。"""
        if not HAS_WIN32:
            return None
        try:
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            if not hwnd:
                return None
            buf = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, buf, 512)
            title = buf.value or ""
            if not title:
                return None
            low = title.lower()
            for needle, name, kind in AI_SIGNATURES:
                if needle in low or needle in title:
                    return (name, kind, hwnd)
        except Exception:
            pass
        return None

    def _poll_ai_app(self, now):
        """每 1 秒看一眼前台是不是某个 AI，换过去了就反应。

        两个关键点（之前这里坑过）：
        1. **睡着时也检测**。检测到 AI 是外部事件，不该算「用户没互动」，
           否则它睡着 → 停止检测 → 永远不知道你在用 AI → 永远醒不过来。
        2. **用「名字 + 窗口句柄」判断变没变**，不只是名字。
           在同一个 AI 里换标签页、换窗口也算变化，反应更灵敏。
        """
        if now < self._ai_next_poll:
            return
        self._ai_next_poll = now + AI_POLL_SEC

        if self.dragging or self.fish_mode != "none":
            return

        found = self._detect_ai_app()
        name = found[0] if found else None
        hwnd = found[2] if found else 0

        sleeping = (now - self.last_action) > 25
        # 睡着而且前台不是 AI：什么都不做，让它继续睡
        if sleeping and not name:
            return

        key = (name, hwnd)
        if key == self._ai_key:
            return
        self._ai_key = key
        self.ai_app = name

        if not name:
            return

        if sleeping:
            # 被 AI 的动静叫醒
            self.last_action = now - 20
            self._touch(hearts=1, jump=1.4)
        self._react_to_ai(name, found[1], now)

    def _react_to_ai(self, name, kind, now):
        """切到某个 AI 了：自己家就得意，别家就吃醋。

        冷却按「每个 AI 分别记」——以前是全局一个计时器，
        在 A 说完话 8 秒内切到 B，B 就被吞掉了，表现就是「醒了但不说」。
        """
        last = self._ai_said.get(name, 0.0)
        if now - last < AI_SAY_COOLDOWN:
            return
        self._ai_said[name] = now

        if kind == "home":
            # 自己家：骄傲、凑上去
            self._touch(hearts=3, jump=2.2)
            self.tilt = 0.0
            self._say(random.choice(AI_HOME_LINES), 2.8)
        else:
            # 别家：扭头、斜眼、吃醋
            lines = AI_OTHER_LINES.get(name) or AI_OTHER_LINES["*"]
            self._say(random.choice(lines), 2.8)
            self.tilt = -0.45
            self._sulk_until = now + 3.0     # 别扭一会儿

    def _step_physics(self):
        """按固定步长推进一次物理。

        跳跃、爱心、悬停、倾斜这些都是「每步变多少」的量，
        以前直接写在渲染循环里，帧率一变速度就跟着变
        （42fps 和 12fps 差 3.5 倍）。现在统一由这里按 60Hz 推进。
        """
        # 跳跃
        if self.bob < 0 or self.bob_v < 0:
            self.bob += self.bob_v
            self.bob_v += 0.42
            if self.bob >= 0:
                self.bob = 0.0
                self.bob_v = 0.0

        # 爱心上浮与消散
        for h in self.hearts:
            h["dy"] -= h["v"]
            h["life"] -= 0.011
        if self.hearts:
            self.hearts = [h for h in self.hearts if h["life"] > 0]

        # 悬停渐变
        self.hover += (self.hover_target - self.hover) * 0.18

        # 拖动倾斜回正（飞行时由 _step_flight 自己控制倾斜）
        if not self.dragging and not self._flying:
            self.tilt *= 0.90

    # ---------------------------------------------------------- 睡 → 醒 → 潜水
    def _update_sleep_dive(self, now, sleepy):
        """睡着满 1 分钟自己醒；醒来 30 秒没人碰，就潜下去。"""
        # 记录从什么时候开始睡的
        if sleepy > 0.6:
            if not self._asleep_since:
                self._asleep_since = now
        else:
            self._asleep_since = 0.0

        # 睡够了，自己醒（不是被戳醒的）
        if self._asleep_since and now - self._asleep_since >= SLEEP_TO_WAKE_SEC:
            self._asleep_since = 0.0
            self._self_woke_at = now
            # 把 last_action 往前拨一点，让它从「熟睡」退回「刚醒的迷糊」
            self.last_action = now - 20
            self._touch(hearts=2, jump=1.6)
            self._say(random.choice(AUTO_WAKE_LINES), 2.2)

        # 自己醒之后 30 秒没人碰 -> 潜水
        if (self._self_woke_at and self.dive_phase is None
                and now - self._self_woke_at >= WAKE_TO_DIVE_SEC
                and now - self.last_action >= WAKE_TO_DIVE_SEC
                and now - self._last_dive_at > DIVE_COOLDOWN_SEC):
            self._start_dive(now)

    def _start_dive(self, now):
        rc = self._win_rect()
        if not rc:
            return
        self._dive_from = (rc[0], rc[1])
        self._dive_depth = WIN * DIVE_DEPTH_RATIO
        self._dive_t0 = now
        self.dive_phase = "down"
        self._self_woke_at = 0.0
        self._say(random.choice(DIVE_LINES), 1.6)

    def _step_dive(self, now):
        """潜水动画：加速下沉 -> 水下停一会儿 -> 慢慢浮上来。

        下沉用 t² （重力，越落越快），上浮用 (1-t)²（浮力，越近水面越慢），
        这样才像水里的东西，不是升降机。
        """
        if not self.dive_phase:
            return
        x0, y0 = self._dive_from
        depth = self._dive_depth
        el = now - self._dive_t0

        if self.dive_phase == "down":
            p = clamp(el / DIVE_DOWN_SEC, 0.0, 1.0)
            self._move_main(x0, y0 + depth * p * p)     # 加速下沉
            self.tilt = -0.85                            # 头朝下
            if p >= 1.0:
                self.dive_phase = "hold"
                self._dive_t0 = now
        elif self.dive_phase == "hold":
            # 沉在下面，身体随水轻轻晃
            self._move_main(x0, y0 + depth)
            self.tilt = -0.30 + math.sin(now * 2.2) * 0.28
            if el >= DIVE_HOLD_SEC:
                self.dive_phase = "up"
                self._dive_t0 = now
        elif self.dive_phase == "up":
            p = clamp(el / DIVE_UP_SEC, 0.0, 1.0)
            self._move_main(x0, y0 + depth * (1.0 - p) * (1.0 - p))   # 减速上浮
            self.tilt = 0.40 * math.sin(p * math.pi)     # 仰头
            if p >= 1.0:
                self.dive_phase = None
                self._move_main(x0, y0)
                self.tilt = 0.0
                self._last_dive_at = now
                self._touch(hearts=2, jump=1.4)
                self._say(random.choice(SURFACE_LINES), 2.0)

    def _cancel_dive(self):
        """用户碰它了：立刻从水里回来，不硬撑着把动画放完。"""
        if not self.dive_phase:
            return
        self.dive_phase = None
        self._last_dive_at = time.time()
        self.tilt = 0.0
        x0, y0 = self._dive_from
        self._move_main(x0, y0)

    def _virtual_screen(self):
        """整个虚拟桌面的范围（跨多显示器时的外接矩形）。"""
        try:
            u = ctypes.windll.user32
            return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),   # X, Y
                    u.GetSystemMetrics(78), u.GetSystemMetrics(79))   # W, H
        except Exception:
            return (0, 0, WIN * 2, WIN * 2)

    def _step_flight(self, now):
        """甩出去之后的飞行：减速 + 撞边回弹，慢到一定程度自己停。"""
        rc = self._win_rect()
        if not rc:
            self._flying = False
            return
        # 用真实时间差推进，卡顿时最多按 100ms 算，避免瞬移
        dt = now - self._last_flight_t
        if dt <= 0:
            dt = 0.016
        dt = min(dt, 0.1)
        self._last_flight_t = now

        x, y = rc[0], rc[1]
        vx, vy = self._fly_vel
        nx, ny = x + vx * dt, y + vy * dt

        sx, sy, sw, sh = self._virtual_screen()
        hit = False
        if nx < sx:
            nx, vx, hit = sx, -vx * BOUNCE, True
        elif nx + WIN > sx + sw:
            nx, vx, hit = sx + sw - WIN, -vx * BOUNCE, True
        if ny < sy:
            ny, vy, hit = sy, -vy * BOUNCE, True
        elif ny + WIN > sy + sh:
            ny, vy, hit = sy + sh - WIN, -vy * BOUNCE, True

        # 撞墙了，喊一声（节流，免得贴着边撞出一串气泡）
        if hit and now - self._last_bounce_say > 0.8:
            self._last_bounce_say = now
            self._say(random.choice(BOUNCE_LINES), 1.5)

        # 指数衰减：每秒乘 e^-FLY_FRICTION
        damp = math.exp(-FLY_FRICTION * dt)
        vx *= damp
        vy *= damp

        if math.hypot(vx, vy) < FLY_STOP_SPEED:
            self._flying = False
            vx = vy = 0.0
            self.tilt = 0.0
            # 落地报个到。刚翻过脸的就别再卖萌了
            if self._throw_count < 3:
                self._say(random.choice(LAND_LINES), 2.0)
        else:
            # 飞的时候顺着方向歪
            self.tilt = clamp(vx * 0.0015, -1.0, 1.0)

        self._fly_vel = (vx, vy)
        self._move_main(nx, ny)

    def on_double(self, ev):
        self._touch(hearts=4, jump=3.6)

    def on_right(self, ev):
        if self.fish_mode == "carrying":
            # 叼着鱼的时候右键 = 把鱼收回去，不弹菜单
            self._cancel_carry()
            return
        self._refresh_menu()
        try:
            self.menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            self.menu.grab_release()

    def _cancel_carry(self):
        self.fish_mode = "none"
        self._close_fish_window()

    def on_enter(self, ev):
        self.hover_target = 1.0
        self.last_action = time.time()

    def on_leave(self, ev):
        self.hover_target = 0.0

    def on_motion(self, ev):
        px = self.root.winfo_pointerx() - self.root.winfo_x()
        py = self.root.winfo_pointery() - self.root.winfo_y()
        self.look = (clamp((px - WIN * 0.46) / (WIN * 0.34), -1, 1),
                     clamp((py - WIN * 0.46) / (WIN * 0.30), -1, 1))
        self.last_action = time.time()

    # ---------------------------------------------------------- 记忆
    @property
    def affection(self):
        """好感度：摸头 + 喂食 + 认识的天数。"""
        return (self.state["pets"] + self.state["feeds"] * 2
                + self.days_known() * 3)

    def days_known(self):
        return max(0.0, (time.time() - self.state["first_met"]) / 86400.0)

    def day_number(self):
        """给人看的「第几天」。

        刚认识那天就算第 1 天，不是第 0 天——没人会说「我们认识 0 天」。
        注意 days_known() 不能改，好感度是按实际经过的天数算的，
        这里只是显示用的偏移。
        """
        return int(self.days_known()) + 1

    def bond_level(self):
        a = self.affection
        if a >= 60:
            return "黏人", 4
        if a >= 30:
            return "亲近", 3
        if a >= 10:
            return "熟悉", 2
        return "刚认识", 1

    def _save_state(self, force=False):
        now = time.time()
        if not force and now - self.last_save < 4:
            return
        self.last_save = now
        self.state["total_seconds"] = self.state.get("total_seconds", 0.0) + (now - self.started_at)
        self.started_at = now
        self.state["last_seen"] = now
        # 记住这会儿待的地方，下次启动直接回到原处。
        # 只在窗口真正摆好之后才记，否则会把启动瞬间的 (0,0) 存进去。
        if self._pos_ready:
            rc = self._win_rect()
            if rc:
                self.state["pos"] = [rc[0], rc[1]]
        # 原子写入：先写临时文件再替换。直接覆盖的话，
        # 写到一半被强杀就会留下半个 json，整份记忆都没了。
        tmp = STATE_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    # ---------------------------------------------------------- 动作
    def pet_head(self):
        self.state["pets"] += 1
        self._touch(hearts=3, jump=1.4, jumps=2)   # 摸头开心，蹦两下
        self._save_state()

    # ---------------------------------------------------------- 喂鱼
    def _lbutton_pressed(self):
        if not HAS_WIN32:
            return False
        try:
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False

    def _cursor_pos(self):
        """鼠标的物理屏幕坐标（Tk 的 winfo_pointer* 在 DPI 缩放下会漂）。"""
        if HAS_WIN32:
            try:
                p = _POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
                return (p.x, p.y)
            except Exception:
                pass
        return (self.root.winfo_pointerx(), self.root.winfo_pointery())

    def _move_main(self, x, y):
        """把鲸鱼窗口挪过去。只用 geometry：SetWindowPos 对 Tk 的窗口句柄
        可能返回 0（ERROR_INVALID_WINDOW_HANDLE），静默失败反而更难查。"""
        try:
            self.root.geometry(f"+{int(x)}+{int(y)}")
        except tk.TclError:
            pass

    def _move_fish_win(self, x, y):
        """把小鱼窗口挪到屏幕坐标。

        注意：Tk 给 Toplevel 的 wrapper 句柄不吃 SetWindowPos
        （会返回 ERROR_INVALID_WINDOW_HANDLE），只能走 geometry。
        好在这台机器上 Tk 坐标和 GetCursorPos 完全一致，所以直接用。
        """
        if self.fish_win is None:
            return
        try:
            self.fish_win.geometry(f"{FISH_W}x{FISH_H}+{int(x)}+{int(y)}")
        except tk.TclError:
            pass

    def start_carrying(self):
        """点了「喂一条小鱼」：鱼叼到鼠标上，点左键放下。"""
        self._cancel_dive()
        if self.fish_mode != "none":
            return
        self.fish_mode = "carrying"
        # 菜单那一下左键可能还按着，先记下真实状态，等它松开才算「放下」
        self._lbtn_down = self._lbutton_pressed()
        self._carry_ready_at = time.time() + 0.35
        self._ensure_fish_window()
        self._touch(hearts=1)
        self.last_action = time.time()

    def _ensure_fish_window(self):
        if self.fish_win is not None:
            return
        try:
            w = tk.Toplevel(self.root)
            w.overrideredirect(True)
            w.wm_attributes("-topmost", True)
            w.configure(bg=BG_HEX)
            try:
                w.wm_attributes("-transparentcolor", BG_HEX)
            except tk.TclError:
                pass
            lbl = tk.Label(w, bd=0, bg=BG_HEX, highlightthickness=0)
            lbl.pack()
            # pack 之后才定尺寸，否则会被内容大小覆盖
            w.geometry(f"{FISH_W}x{FISH_H}+0+0")
            w.update_idletasks()
            w.geometry(f"{FISH_W}x{FISH_H}+0+0")

            # 鼠标穿透：鱼只是跟着指针看，不挡点击。
            # wm_frame() 才是这个 Toplevel 真正的顶层 HWND。
            if HAS_WIN32:
                try:
                    u = ctypes.windll.user32
                    hwnd = int(w.wm_frame(), 16)
                    ex = u.GetWindowLongW(hwnd, -20)
                    u.SetWindowLongW(hwnd, -20, ex | 0x00080000 | 0x00000020)
                except Exception:
                    pass

            self.fish_win = w
            self.fish_label = lbl
        except tk.TclError:
            self.fish_win = None
            self.fish_label = None

    def _close_fish_window(self):
        if self.fish_win is not None:
            try:
                self.fish_win.destroy()
            except tk.TclError:
                pass
        self.fish_win = None
        self.fish_label = None
        self.fish_photo = None

    def _update_carrying(self, now, t):
        if self.fish_win is None:
            return

        # 全部用物理屏幕坐标，免得 DPI 缩放把 Tk 的逻辑坐标和窗口位置错开
        mx, my = self._cursor_pos()
        self._move_fish_win(mx + FISH_OFFSET_X, my + FISH_OFFSET_Y)

        # 尾巴甩起来（左键按住时它会受惊）
        pressed = self._lbutton_pressed()
        try:
            img = render_fish(t, scared=pressed)
            self.fish_photo = ImageTk.PhotoImage(img)
            self.fish_label.configure(image=self.fish_photo)
        except tk.TclError:
            return

        # 鲸鱼一直盯着那条鱼
        rc = self._win_rect()
        if rc:
            dx = mx - (rc[0] + rc[2] // 2)
            dy = my - (rc[1] + rc[3] // 2)
            dist = max(1.0, math.hypot(dx, dy))
            self.look = (clamp(dx / dist, -1, 1), clamp(dy / dist, -1, 1))

        # 左键一按下就把鱼放下（不等松开）。轮询是按帧采样的，
        # 等“按下→松开”一个完整周期的话，手点快一点就会整个漏过去。
        if now >= self._carry_ready_at and pressed and not self._lbtn_down:
            self._lbtn_down = True
            self._drop_fish()

    def _drop_fish(self):
        if self.fish_mode != "carrying":
            return
        mx, my = self._cursor_pos()
        # 鱼的中心（鲸鱼要游到这个点来吃）
        self.fish_pos = (mx + FISH_OFFSET_X + FISH_W // 2,
                         my + FISH_OFFSET_Y + FISH_H // 2)
        rc = self._win_rect()
        self.fish_mode = "swimming"
        # 鱼就停在跟随时的那个位置——不能用「中心对准光标」，
        # 否则松手那一瞬间鱼会往左上跳 41×31 像素，看着像放偏了。
        self._move_fish_win(mx + FISH_OFFSET_X, my + FISH_OFFSET_Y)

    def _swim_step(self):
        if self.fish_mode != "swimming" or not self.fish_pos:
            return
        rc = self._win_rect()
        if not rc:
            return
        cx, cy, w, h = rc
        fx, fy = self.fish_pos
        dx = (fx - w // 2) - cx
        dy = (fy - h // 2) - cy
        dist = math.hypot(dx, dy)
        if dist < 16:
            self._eat_fish()
            return
        step = min(dist, 14)
        self._move_main(cx + dx / dist * step, cy + dy / dist * step)
        self.look = (clamp(dx / dist, -1, 1), clamp(dy / dist, -1, 1))

    def _say(self, text, seconds=3.5, urgent=False):
        """开口说一句。

        默认不打断正在说的：当前气泡还没消失就先排队，挨个播完。
        这样甩飞时「啊啊啊——」「哎哟！」「晕…」能一条条看到，
        而不是被后一句直接顶掉。urgent=True 时无条件抢断。
        """
        now = time.time()
        if urgent or now >= self.bubble_until:
            self.bubble_text = text
            self.bubble_until = now + seconds
            self.next_bubble = now + random.uniform(35, 80)
            return
        # 排队，最多攒 2 句，多了丢最旧的，免得堆成一大串
        self._say_queue.append((text, seconds))
        if len(self._say_queue) > 2:
            self._say_queue.pop(0)

    def _eat_fish(self):
        # 吃完就地待着，不再游回原位
        self.fish_mode = "none"
        self._close_fish_window()
        self.state["feeds"] += 1
        self._save_state()
        self._touch(hearts=6, jump=2.4, jumps=2)   # 吃到了，高兴地蹦两下

        self.last_feed_at = time.time()
        self._hungry_said = False
        self.feed_streak += 1
        if self.feed_streak >= 3:
            self.feed_streak = 0
            self._say("吃的好饱 最喜欢主人了", 4.5)

    def next_skin(self):
        self.skin_idx = (self.skin_idx + 1) % len(SKINS)

    def make_sleepy(self):
        """哄它睡觉：把上次互动时间往前拨，它就会自己打瞌睡。窗口不会消失。"""
        self.last_action = time.time() - 60

    # ---------------------------------------------------------- 情境台词
    def _time_bucket(self, now):
        h = time.localtime(now).tm_hour
        if h < 5:
            return "late_night"
        if h < 9:
            return "morning"
        if h < 12:
            return "forenoon"
        if h < 14:
            return "noon"
        if h < 18:
            return "afternoon"
        if h < 22:
            return "evening"
        return "night"

    def _context_lines(self, now):
        """挑几句「此时此刻」才成立的话；没有合适的就返回空列表。"""
        out = list(CONTEXT_LINES.get(self._time_bucket(now), ()))
        session = now - self.session_start
        for threshold, lines in SESSION_LINES:
            if session >= threshold:
                out += lines
                break
        return out

    # ---------------------------------------------------------- 小动作
    def _maybe_start_gesture(self, now, sleepy):
        """闲下来够久了，就挑一个小动作做做，别让它一直傻站着。"""
        if self.gesture or self.dragging or self.fish_mode != "none":
            return
        if sleepy > 0.4 or now < self.next_gesture:
            return
        name = random.choice(("look_around", "tail_flick", "shiver",
                              "yawn", "stretch"))
        dur = {"look_around": 1.7, "tail_flick": 0.9, "shiver": 0.55,
               "yawn": 1.9, "stretch": 1.5}[name]
        self.gesture = name
        self.gesture_start = now
        self.gesture_dur = dur
        if name == "look_around":
            self.gesture_look = (random.choice((-1, 1)) * random.uniform(0.35, 0.9),
                                 random.uniform(-0.45, 0.45))
        self.next_gesture = now + dur + random.uniform(4, 13)

    def _gesture_state(self, now):
        """把当前小动作翻译成渲染参数。

        返回 (squash, tail_extra, look_bias, force_blink)
        """
        if not self.gesture:
            return 0.0, 0.0, None, False
        p = clamp((now - self.gesture_start) / max(1e-3, self.gesture_dur), 0.0, 1.0)
        if p >= 1.0:
            self.gesture = None
            return 0.0, 0.0, None, False

        name = self.gesture
        env = math.sin(p * math.pi)          # 起落都归零的包络，不会突兀
        if name == "shiver":
            return math.sin(p * math.pi * 6) * 0.085, 0.0, None, False
        if name == "tail_flick":
            return 0.0, abs(math.sin(p * math.pi * 2)) * 1.1, None, False
        if name == "yawn":
            # 没有嘴了，打哈欠靠「闭眼 + 身体拉长 + 视线下垂」表达
            return -env * 0.07, env * 0.2, (0.0, -0.12), True
        if name == "stretch":
            return -env * 0.10, env * 0.45, None, False
        if name == "look_around":
            return 0.0, 0.0, (self.gesture_look[0] * env,
                              self.gesture_look[1] * env), False
        return 0.0, 0.0, None, False

    def _clamp_to_screen(self, x, y, w, h):
        """把窗口左上角夹在虚拟屏幕范围内，至少露出大半，防止拖出去就找不回来。"""
        if not HAS_WIN32:
            return int(x), int(y)
        try:
            u = ctypes.windll.user32
            vx = u.GetSystemMetrics(76)    # SM_XVIRTUALSCREEN
            vy = u.GetSystemMetrics(77)    # SM_YVIRTUALSCREEN
            vw = u.GetSystemMetrics(78)    # SM_CXVIRTUALSCREEN
            vh = u.GetSystemMetrics(79)    # SM_CYVIRTUALSCREEN
            if vw <= 0 or vh <= 0:
                return int(x), int(y)
            keep_x = int(w * 0.55)         # 至少露 55%
            keep_y = int(h * 0.55)
            minx = vx - w + keep_x
            maxx = vx + vw - keep_x
            miny = vy - h + keep_y
            maxy = vy + vh - keep_y
            return int(clamp(x, minx, maxx)), int(clamp(y, miny, maxy))
        except Exception:
            return int(x), int(y)

    def _ensure_visible(self):
        """两个自愈：窗口被隐藏就冒出来；被拖到屏幕外就拽回来。"""
        if self._hidden_fs or not self.hwnd:
            return
        # 潜水时窗口故意沉到屏幕外，别把它拽回来
        if self.dive_phase:
            return
        try:
            u = ctypes.windll.user32
            if not u.IsWindowVisible(self.hwnd):
                self.root.deiconify()
                self._keep_on_top()
                return

            rc = self._win_rect()
            if not rc:
                return
            x, y, w, h = rc
            vx = u.GetSystemMetrics(76)
            vy = u.GetSystemMetrics(77)
            vw = u.GetSystemMetrics(78)
            vh = u.GetSystemMetrics(79)
            # 整扇窗都在虚拟屏幕之外 → 拽回边界
            if (x + w < vx or x > vx + vw or y + h < vy or y > vy + vh):
                nx, ny = self._clamp_to_screen(x, y, w, h)
                self._move_main(nx, ny)
                self._keep_on_top()
        except Exception:
            pass

    def _foreground_is_fullscreen(self):
        """前台是不是一个占满整个显示器（连任务栏都盖掉）的全屏程序。

        最大化窗口只盖住工作区、会把任务栏让出来，所以不会被误判成全屏。
        """
        if not HAS_WIN32 or not self.hwnd:
            return False
        try:
            u = ctypes.windll.user32
            fg = u.GetForegroundWindow()
            if not fg or fg == self.hwnd:
                return False

            buf = ctypes.create_unicode_buffer(64)
            u.GetClassNameW(fg, buf, 64)
            if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd",
                             "Shell_SecondaryTrayWnd"):
                return False

            r = _RECT()
            if not u.GetWindowRect(fg, ctypes.byref(r)):
                return False
            mon = u.MonitorFromWindow(fg, 2)      # MONITOR_DEFAULTTONEAREST
            if not mon:
                return False
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if not u.GetMonitorInfoW(mon, ctypes.byref(mi)):
                return False

            m = mi.rcMonitor
            return (r.left <= m.left and r.top <= m.top and
                    r.right >= m.right and r.bottom >= m.bottom)
        except Exception:
            return False

    def _win_rect(self):
        """当前窗口的物理矩形 (x, y, w, h)。"""
        if not HAS_WIN32 or not self.hwnd:
            return None
        try:
            r = _RECT()
            if not ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(r)):
                return None
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception:
            return None

    def _check_fullscreen(self):
        """全屏程序在前台就躲起来，切回来再冒出来（原地不动）。"""
        if not HAS_WIN32 or not self.hwnd:
            return
        fs = self._foreground_is_fullscreen()
        try:
            if fs and not self._hidden_fs:
                self._hidden_fs = True
                self._rect_before_hide = self._win_rect()
                self.root.withdraw()
            elif not fs and self._hidden_fs:
                self._hidden_fs = False
                self.root.deiconify()
                # withdraw/deiconify 会让位置漂移，按躲起来之前的坐标摆回去
                rc = getattr(self, "_rect_before_hide", None)
                if rc:
                    x, y, w, h = rc
                    ctypes.windll.user32.SetWindowPos(
                        self.hwnd, -1, x, y, w, h, 0x0010)
                self._keep_on_top()
        except tk.TclError:
            pass

    def quit(self):
        self._close_fish_window()
        self._save_state(force=True)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ---------------------------------------------------------- 主循环
    def tick(self):
        # 兜底：不管这一帧里哪一步抛了异常，都要保证下一帧还会来，
        # 否则一次报错就会把整只鲸鱼冻住（喂鱼时最容易踩到）。
        t0 = time.perf_counter()
        try:
            self._tick_once()
        except Exception:
            import traceback
            _log_error(time.strftime("%Y-%m-%d %H:%M:%S ") + "tick\n"
                       + traceback.format_exc() + "\n")
        finally:
            # 按本帧实际耗时反推该等多久，而不是死等一个固定值：
            # 渲染快了就能跑得更顺，偶尔卡一下也不会累积漂移。
            elapsed = (time.perf_counter() - t0) * 1000.0
            frame_ms = getattr(self, "_frame_ms", TARGET_FRAME_MS)
            delay = max(1, int(round(frame_ms - elapsed)))
            try:
                self.root.after(delay, self.tick)
            except tk.TclError:
                pass

    def _tick_once(self):
        now = time.time()
        t = now - self.t0
        idle = now - self.last_action

        # 因为全屏程序躲起来了：不渲染、不做任何动画，
        # 只保留「全屏是不是结束了」的检测，不然它永远回不来。
        if self._hidden_fs:
            if self._tick_n % 30 == 0:
                self._check_fullscreen()
            self._tick_n += 1
            return

        # 空闲降帧：没人理的时候不用烧 42fps，12fps 看不出区别
        busy = (idle < IDLE_AFTER_SEC or self.dragging
                or self.fish_mode != "none" or self.hearts)
        self._frame_ms = TARGET_FRAME_MS if busy else IDLE_FRAME_MS

        # 所有按帧推进的量（跳跃、爱心、悬停、倾斜）统一走固定 60Hz 步长，
        # 这样 42fps 和 12fps 下物理速度完全一致。
        self._phys_acc += now - self._last_tick
        self._last_tick = now
        if self._phys_acc > 0.5:
            self._phys_acc = 0.5          # 长时间挂起后别一次补太多
        steps = 0
        while self._phys_acc >= PHYS_STEP and steps < 30:
            self._phys_acc -= PHYS_STEP
            self._step_physics()
            steps += 1

        # 眨眼
        if now > self.next_blink:
            self.blink_until = now + 0.13
            self.next_blink = now + random.uniform(2.5, 6.0)
        blink = now < self.blink_until

        # 太久没互动 -> 打瞌睡
        sleepy = clamp((idle - 25) / 10.0, 0.0, 1.0)
        if sleepy > 0.6:
            self.look = (0.0, 0.0)
            blink = True

        # 睡够了自己醒；醒来一直没人理就潜水
        self._update_sleep_dive(now, sleepy)
        self._step_dive(now)
        if self.dive_phase:
            # 潜水期间：不做别的动作，专心往下游
            self._frame_ms = TARGET_FRAME_MS
            img = render_frame(
                t, SKINS[self.skin_idx], (0.0, 0.35), False,
                bob=0.0, tilt=self.tilt, hover=0.0,
                mood="idle", hearts=None, bubble=None, zzz=0.0,
                squash=0.0, tail_extra=1.15, spout=0.0)
            self.photo = ImageTk.PhotoImage(img)
            self.label.configure(image=self.photo)
            self._tick_n += 1
            return

        # 饿了三分钟会自己开口
        if (not self._hungry_said and self.fish_mode == "none"
                and now - self.last_feed_at > 180):
            self._hungry_said = True
            self._say("主人 饿饿 想吃鱼鱼", 4.0)

        # 气泡
        if now > self.next_bubble and not self.dragging:
            d = self.days_known()
            name, lv = self.bond_level()
            if sleepy > 0.6:
                # 睡着时说的都是梦话，跟清醒时完全两套
                lines = ["嘿嘿 把你的鱼鱼吃光光", "啊 好多小鱼鱼啊",
                         "别跑…那条是我的…", "唔…主人…再给一条嘛",
                         "呼…呼…鱼鱼…", "这条大的…留给我…"]
            else:
                lines = ["要记得喝水呀", "我在呢", "今天也辛苦啦", "这个 bug 会修好的",
                         "歇一会儿吧", "别熬太晚啦", "嗯…我在想事情"]
                if d >= 1:
                    lines.append("我们认识 %d 天啦" % self.day_number())
                if lv >= 3:
                    lines += ["今天也想多看你一会儿", "你在的时候我就不乱动"]
                elif lv <= 1:
                    lines += ["……你好呀", "有点陌生，但没关系"]
                # 有四成概率改说"此时此刻"才成立的话，而不是永远那几句
                ctx = self._context_lines(now)
                if ctx and random.random() < 0.45:
                    lines = ctx
            self.bubble_text = random.choice(lines)
            self.bubble_until = now + 3.2
            # 越亲近越爱说话
            self.next_bubble = now + random.uniform(35, 80) / (1.0 + (lv - 1) * 0.35)

        # 排队的台词：上一句播完就接下一句
        if now >= self.bubble_until and self._say_queue:
            next_text, next_secs = self._say_queue.pop(0)
            self.bubble_text = next_text
            self.bubble_until = now + next_secs

        bubble = self.bubble_text if now < self.bubble_until else None

        # 喂鱼这条线
        if self.fish_mode == "carrying":
            self._update_carrying(now, t)
        elif self.fish_mode == "swimming":
            self._swim_step()

        # 悬停渐变、跳跃、爱心、倾斜回正都在 _step_physics 里按固定 60Hz 推进

        # 连跳：落地后如果还有余量，隔一小会儿再蹦一下
        if (self._jumps_left > 0 and self.bob == 0.0 and self.bob_v == 0.0
                and now >= self._next_jump_at):
            self._jumps_left -= 1
            self.bob_v = -self._jump_power
            self._next_jump_at = now + 0.10

        # 甩抛飞行（优先级最高：飞的时候别的位移都别掺和）
        if self._flying and not self.dragging:
            self._step_flight(now)
        elif self._flying and self.dragging:
            self._flying = False        # 飞行途中被抓住

        # 喷水：隔一阵子喷 0.9 秒，睡熟了不喷
        spout = 0.0
        if now < self.spout_until:
            p = 1.0 - (self.spout_until - now) / 0.9
            spout = math.sin(clamp(p, 0.0, 1.0) * math.pi)
        elif now > self.next_spout and sleepy < 0.35 and not self.dragging:
            self.spout_until = now + 0.9
            self.next_spout = now + random.uniform(9, 22)
            spout = math.sin(0.02 * math.pi)

        # 小动作（扭头 / 甩尾 / 抖一下 / 打哈欠 / 伸懒腰）
        self._maybe_start_gesture(now, sleepy)
        g_squash, g_tail, g_look, g_blink = self._gesture_state(now)

        # 看一眼前台是不是换了 AI（只在切换时反应一次）
        self._poll_ai_app(now)

        # 吃醋的时候扭头不看，别扭几秒
        if now < self._sulk_until:
            self.tilt = -0.45
            if self.hover < 0.3:
                self.look = (-0.85, -0.15)

        # 爱心的存续也会影响表情
        mood = "happy" if self.hearts else "idle"

        # 视线优先级：鼠标 > 小动作
        look = self.look
        if g_look is not None:
            look = (self.look[0] + g_look[0], self.look[1] + g_look[1])
        look = (clamp(look[0], -1.0, 1.0), clamp(look[1], -1.0, 1.0))
        if g_blink:
            blink = True

        img = render_frame(
            t, SKINS[self.skin_idx], look, blink,
            bob=self.bob, tilt=self.tilt, hover=self.hover,
            mood=mood, hearts=self.hearts, bubble=bubble, zzz=sleepy,
            squash=g_squash, tail_extra=g_tail, spout=spout,
        )
        self.photo = ImageTk.PhotoImage(img)
        self.label.configure(image=self.photo)

        self._tick_n += 1
        if self._tick_n % 30 == 0:
            self._check_fullscreen()      # 有全屏程序就躲起来
            if not self._hidden_fs:
                self._keep_on_top()
                self._ensure_visible()
        if self._tick_n % 1800 == 0:      # 约 1 分钟存一次档
            self._save_state()

    def run(self):
        self.root.mainloop()


# ================================================================ 预览
def preview():
    out = os.path.join(ROOT, "assets", "preview.png")
    states = [
        dict(t=0.0, look=(0, 0), blink=False, hover=0.0),
        dict(t=1.0, look=(0.8, -0.4), blink=False, hover=0.8),
        dict(t=2.0, look=(-0.6, 0.5), blink=True, hover=0.2),
        dict(t=3.0, look=(0, 0), blink=False, hover=0.4, mood="happy",
             hearts=[{"dx": -8, "dy": 6, "r": 4, "life": 0.9},
                     {"dx": 6, "dy": 0, "r": 3, "life": 1.0}]),
        dict(t=4.0, look=(0, 0), blink=True, hover=0.0, zzz=1.0,
             bubble="今天也辛苦啦"),
    ]
    t0 = time.time()
    frames = [render_frame(**st, skin=SKINS[0]) for st in states]
    dt = (time.time() - t0) / len(states)
    sheet = Image.new("RGB", (WIN * len(frames), WIN), (14, 18, 30))
    for i, f in enumerate(frames):
        sheet.paste(f, (WIN * i, 0))
    sheet = sheet.resize((sheet.width * 2, sheet.height * 2), Image.LANCZOS)
    sheet.save(out)
    print("预览已保存:", out)
    print("单帧渲染耗时: %.1f ms  (30fps 预算 33ms)" % (dt * 1000))


def _acquire_single_instance():
    """拿一个命名互斥体，保证同一台机器上只养一只鲸鱼。

    返回互斥体句柄（要一直留着，否则会被回收）；已经有一只了则返回 None。
    """
    if not HAS_WIN32:
        return -1
    try:
        k = ctypes.windll.kernel32
        handle = k.CreateMutexW(None, False, "Local\\DeepSeekWhalePet_SingleInstance")
        if k.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
            return None
        return handle
    except Exception:
        return -1


if __name__ == "__main__":
    if "--preview" in sys.argv:
        preview()
    else:
        _MUTEX = _acquire_single_instance()
        if _MUTEX is None:
            # 已经有一只了（比如开机自启 + 手动点了图标），这次就安静地退出
            sys.exit(0)
        try:
            WhalePet().run()
        except Exception:
            # pythonw 没有控制台，崩溃信息写进日志，不然什么都看不到
            import traceback
            _log_error(time.strftime("%Y-%m-%d %H:%M:%S\n")
                       + traceback.format_exc() + "\n")
            raise


