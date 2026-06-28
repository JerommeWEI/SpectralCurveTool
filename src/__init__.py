# -*- coding: utf-8 -*-
"""SpectralCurveTool —— 源码包。

模块：
- theme: Professional Scientific 主题（配色/字体/圆角按钮/ttk 样式）
- csv_loader: 鲁棒 CSV 解析与曲线数据结构
- app: 主 GUI（数据加载 / 绘图 / 差值 / 校准分析）
"""

from .app import SpectrumApp, launch

__all__ = ['SpectrumApp', 'launch']
