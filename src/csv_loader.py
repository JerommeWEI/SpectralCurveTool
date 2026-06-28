# -*- coding: utf-8 -*-
"""
CSV 鲁棒解析模块。

针对 4108 近红外光谱导出的多种 CSV 头格式统一处理：
- 带 BOM / 不带 BOM
- 首行是无名标题行（`,xxx`），真正表头在第二行
- X 列名：CWL / Wavelength / Wavelength[nm] / 无名
- Y 列名：Intensity / Absorbance / Log(1/R) / White Reference / Dark Current Reference / 无名

核心策略：定位「首个两列均为数值的行」作为数据起点，其上一行即表头；
按表头文本 + Y 值数值范围判定 Y 类型（intensity / absorbance）。
"""

import os
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np


@dataclass
class Curve:
    """一条已解析的曲线。"""
    name: str          # 显示名（文件名 stem）
    x: np.ndarray      # 波长 / CWL
    y: np.ndarray      # 强度 / 吸光度
    y_type: str        # 'intensity' | 'absorbance'
    path: str
    y_label: str = ''  # 原始 Y 列名（图例辅助）

    @property
    def n_points(self) -> int:
        return len(self.x)


def _try_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _detect_y_type(header_text: str, y_values: np.ndarray) -> str:
    """判定 Y 类型：优先表头文本，其次数值范围。"""
    h = (header_text or '').lower()
    if 'absorb' in h or 'log(1/r)' in h or 'log(1/r)' in h or '1/r' in h:
        return 'absorbance'
    if 'intensity' in h or 'reference' in h or 'dark' in h or 'reflect' in h or 'transm' in h:
        return 'intensity'
    # 兜底：吸光度通常 < 5，强度通常 > 50
    finite = y_values[np.isfinite(y_values)]
    if finite.size:
        med = float(np.median(np.abs(finite)))
        return 'intensity' if med > 50 else 'absorbance'
    return 'intensity'


def load_curve(path: str) -> Curve:
    """解析单个 CSV 为 Curve。失败抛出 ValueError。"""
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as f:
        lines = f.read().splitlines()

    # 过滤空行
    rows = [ln for ln in lines if ln.strip() != '']
    if not rows:
        raise ValueError('空文件')

    # 拆行：按逗号/制表符/分号/空白分隔，返回全部字段
    def split_all(line):
        for sep in (',', '\t', ';'):
            if sep in line:
                return [p.strip() for p in line.split(sep)]
        return [p.strip() for p in line.split()]

    def split_two(line):
        parts = split_all(line)
        return (parts[0] if parts else ''), (parts[1] if len(parts) > 1 else '')

    # 定位首个两列均为数值的行
    data_start = -1
    for i, ln in enumerate(rows):
        a, b = split_two(ln)
        if a != '' and b != '' and _try_float(a) is not None and _try_float(b) is not None:
            data_start = i
            break

    if data_start < 0:
        raise ValueError('未找到数值数据行')

    # 宽行检测：单行多数值列（如 demo 导出的 coeffA/coeffB 平铺系数数组）
    # 不是 (波长, 值) 光谱，跳过此类文件。
    first_num_fields = sum(1 for fld in split_all(rows[data_start]) if _try_float(fld) is not None)
    if first_num_fields > 2:
        raise ValueError('非光谱格式（单行系数数组）')

    # 表头：数据起点的上一行
    header_y = ''
    if data_start > 0:
        _, hb = split_two(rows[data_start - 1])
        if _try_float(hb) is None:  # 确认是文字表头而非数据
            header_y = hb

    # 读取全部数据行
    xs, ys = [], []
    for ln in rows[data_start:]:
        a, b = split_two(ln)
        fx, fy = _try_float(a), _try_float(b)
        if fx is None or fy is None:
            continue
        xs.append(fx)
        ys.append(fy)

    if not xs:
        raise ValueError('无有效数值')

    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)

    # 丢弃 NaN
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]

    # 按 X 升序排序（便于插值/对比）
    order = np.argsort(x)
    x, y = x[order], y[order]

    y_type = _detect_y_type(header_y, y)

    name = os.path.splitext(os.path.basename(path))[0]
    return Curve(name=name, x=x, y=y, y_type=y_type, path=path, y_label=header_y)


def _iter_csv_in_dir(dirpath: str):
    """递归收集目录下的 .csv，排除 tmp 文件夹。"""
    out = []
    for root, dirs, files in os.walk(dirpath):
        # 排除 tmp 目录段
        if os.path.basename(root).lower() == 'tmp':
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d.lower() != 'tmp']
        for fn in files:
            if fn.lower().endswith('.csv'):
                out.append(os.path.join(root, fn))
    return out


def load_paths(paths) -> Tuple[List[Curve], List[Tuple[str, str]]]:
    """加载一批路径（文件或文件夹），返回 (curves, errors)。

    errors 为 (路径, 错误信息) 列表。
    """
    csv_files = []
    seen = set()
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for f in _iter_csv_in_dir(p):
                key = os.path.normcase(f)
                if key not in seen:
                    seen.add(key)
                    csv_files.append(f)
        elif os.path.isfile(p) and p.lower().endswith('.csv'):
            key = os.path.normcase(p)
            if key not in seen:
                seen.add(key)
                csv_files.append(p)

    csv_files.sort()
    curves, errors = [], []
    for f in csv_files:
        try:
            curves.append(load_curve(f))
        except Exception as e:
            errors.append((f, str(e)))
    return curves, errors
