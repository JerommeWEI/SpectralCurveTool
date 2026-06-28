# SpectralCurveTool

> 面向 **4108 近红外光谱仪**（2560 像素）导出 CSV 的桌面**对比 / 校准分析**工具。
> 拖拽加载、多曲线叠加、跨量纲对比、差异量化、校准传递（仿射映射 + 加权期望）。
> 基于 Python · tkinter · matplotlib，采用 Professional Scientific 主题。

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-059669)](LICENSE)
[![tkinter](https://img.shields.io/badge/GUI-tkinter%20%2B%20matplotlib-1E3A5F)]()
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()
[![Status](https://img.shields.io/badge/status-v1.0%20internal-2563EB)]()

---

## ✨ 功能特性

- **拖拽加载**：CSV 文件 / 文件夹直接拖入（`tkinterdnd2`），递归收集、自动排除 `tmp/`。
- **多曲线叠加对比**：逐条显隐 / 改色 / 删除，右键菜单，列表与画布颜色联动。
- **跨量纲混排**：原始强度（~千级）与吸光度（~0.2）支持 **双 Y 轴** 或 **0–1 归一化** 对比。
- **差异量化**：相减 / 比值(带下限) / **有界相对偏差 [-1,1]** / **RMSE 评分表**。
- **校准分析**（三个窗口）：
  - **映射 / 校准 A→B**：单组仿射拟合 `B = m·A + c`，三图（原始/映射后/残差）。
  - **批量映射（求平均）**：多组拟合 + **期望(残差倒数加权)** 聚合，每组单独残差子图。
  - **批量校准验证**：套用系数，残差叠加 + **还原曲线对比**（源/校准/目标）。
- **智能配对 S1–S6**：按文件夹 + 变体后缀自动匹配，排除 `_raw`/`_absorbance` 混配。
- **导出**：PNG / 汇总 CSV（公共波长网格）/ 映射结果 CSV / 批量映射 CSV（含平均系数）。
- **鲁棒解析**：自动兼容 4108 各种 CSV 头格式（BOM / 无名标题行 / 多种列名），自动跳过单行系数平铺数组。

> 📖 完整功能与使用说明见 **[`SOP/Guide.html`](SOP/Guide.html)**（浏览器打开即可，工程师上手必读）。

---

## 🧰 环境依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | ≥ 3.9 | `tkinter` 随官方安装包自带 |
| tkinterdnd2 | ≥ 1.7.0 | 原生拖拽（可选；缺失时回退按钮加载） |
| matplotlib | ≥ 3.10 | 绘图后端 TkAgg |
| pandas | ≥ 2.2 | CSV 读写 |
| numpy | ≥ 2.1 | 数值计算 |

---

## 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动（在项目根目录执行）
python run.pyw          # 推荐：pythonw 运行，无控制台黑窗
# 或：双击 run.pyw
```

> ⚠️ 必须**在项目根目录**启动，否则 `src` 包无法正确导入。

加载数据后：
1. 把 CSV 文件 / 文件夹**拖入窗口**（或点「添加文件/文件夹」）。
2. 在曲线列表勾选要对比的曲线。
3. 选 Y 轴模式 / 差值方式；点「校准分析」做映射与验证。

---

## 📂 项目结构

```
SpectralCurveTool/
├── run.pyw              # 🚀 入口（根目录唯一可执行入口）
├── requirements.txt     # 依赖清单
├── ReadMe.md            # 本文件
├── .gitignore
├── src/                 # 源码包
│   ├── __init__.py      # 导出 launch / SpectrumApp
│   ├── theme.py         # Professional Scientific 主题（配色/字体/圆角按钮/ttk 样式）
│   ├── csv_loader.py    # 鲁棒 CSV 解析 + Curve 数据结构 + load_paths
│   └── app.py           # 主 GUI（数据加载/绘图/差值/校准分析三窗口）
└── SOP/
    └── Guide.html       # 详细使用指南（功能/工作流/数学原理/排错）
```

---

## 🏗️ 架构与模块

| 模块 | 职责 |
|------|------|
| `src/theme.py` | 主题常量 `THEME_COLORS` / `THEME_FONTS`、`RoundedButton`（Canvas 圆角按钮）、`apply_theme()`（ttk 全组件样式）。 |
| `src/csv_loader.py` | `load_curve()`（「定位首个全数值行」鲁棒解析）、`load_paths()`（文件/文件夹递归 + `tmp` 排除）、`Curve` 数据类。 |
| `src/app.py` | `SpectrumApp` 主类：主视图（加载/列表/绘图/导出）+ 校准分析三窗口（映射 / 批量映射 / 批量验证）+ 全部绘图与导出逻辑。 |

**入口链路**：`run.pyw` → `from src import launch` → `SpectrumApp(root).mainloop()`。

---

## 🔬 核心数学原理（摘要）

详见 [Guide.html §8](SOP/Guide.html#math)。

- **仿射映射**：归一化后形状一致 ⟺ 原始尺度上 `B = m·A + c`（m=增益，c=基线）。映射即线性回归/仪器校准。
- **加权期望**（反方差合并）：`E[x] = Σwᵢxᵢ/Σwᵢ`，`wᵢ = 1/RMSᵢ²`。残差越小权重越大，**不被离群带偏**，优于等权平均。
- **有界相对偏差**：`D = (y−base)/(|y|+|base|) ∈ [-1,1]`，`0/0` 填 0，避免尖峰。
- **RMSE（归一化）**：`√mean((yₙ−baseₙ)²)`，越小越相似。

---

## 🧪 数据格式说明

4108 导出的 CSV 头格式多样（`CWL` / `Wavelength` / `Wavelength[nm]` / `Intensity` / `Absorbance` / `Log(1/R)`，带 BOM 或无名标题行），本工具自动识别：
- X 列 = 第一列（波长/CWL）；Y 列 = 第二列。
- Y 类型按表头文本 + 数值范围判定（吸光度 < 5，强度 > 50）。
- `4108demo导出` 下的 `coeffA/coeffB.csv` 是单行平铺系数数组（非光谱），自动跳过。

---

## 🛠️ 排错速查

| 现象 | 处理 |
|------|------|
| `ModuleNotFoundError: src` | 未在根目录启动，`cd` 到根目录再运行 |
| 拖拽无反应 | `pip install tkinterdnd2`，或用「添加文件」按钮 |
| 批量验证配对混乱 | 用「智能配对 S1–S6」或「添加配对」显式构建，勿依赖下标 |
| 曲线点数异常（1 点） | 该文件可能非光谱（系数数组），通常已自动跳过 |

更多见 [Guide.html §9](SOP/Guide.html#trouble)。

---

## 📈 开发与扩展

- 新增差值方式：在 `app.py` 的 `_redraw()` 差值分支扩展。
- 新增聚合方式：在 `_aggregate()` 增加 case。
- 新增曲线解析格式：在 `csv_loader.py` 的 `load_curve()` 调整。
- 主题调整：编辑 `theme.py` 的 `THEME_COLORS`。

---

## 📄 License

本项目采用 [MIT License](LICENSE) 开源。

```
MIT License
Copyright (c) 2026 SpectralCurveTool Contributors
```

> 上传公开仓库前，请确认：① 仓库内**不含**任何光谱数据/敏感路径（本项目数据在 OneDrive，`.gitignore` 已默认忽略 `*.csv/*.xlsx/*.json` 等）；② LICENSE 中的版权归属（`SpectralCurveTool Contributors`）按需替换为实际持有人/组织。

---

<sub>维护：SpectralCurveTool · 主题风格参考 Professional Scientific Theme</sub>
