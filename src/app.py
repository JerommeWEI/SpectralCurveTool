# -*- coding: utf-8 -*-
"""
SpectralCurveTool —— 主 GUI。

功能：
- 拖拽 CSV 文件/文件夹（tkinterdnd2，未安装时回退按钮加载）
- 多曲线叠加显示，逐条显隐 / 改色 / 删除
- Y 轴模式：原值 / 0-1 归一化 / 强度·吸光度双 Y 轴
- 差值曲线（选定基准，底部独立子图）
- 内嵌 matplotlib，自带缩放/平移/取值/保存
- 导出 PNG / 导出汇总 CSV（公共波长网格）

主题：Professional Scientific Style（见 theme.py）。
"""

import os
import re
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import numpy as np

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi']
matplotlib.rcParams['axes.unicode_minus'] = False

from .theme import THEME_COLORS as C, THEME_FONTS as F, apply_theme, RoundedButton
from .csv_loader import load_paths, Curve

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False

# 视觉友好的深色调色板（在白色画布上可读）
PALETTE = [
    '#1E3A5F', '#059669', '#DC2626', '#2563EB', '#D97706',
    '#7C3AED', '#0891B2', '#DB2777', '#65A30D', '#EA580C',
    '#4F46E5', '#0D9488', '#BE123C', '#9333EA', '#0369A1',
    '#CA8A04', '#15803D', '#B45309', '#7E22CE', '#BE185D',
]

X_LABEL = '波长 (nm)'
Y_LABEL_RAW = '强度 / 吸光度'
Y_LABEL_INT = '强度'
Y_LABEL_ABS = '吸光度 (Log 1/R)'
Y_LABEL_NORM = '归一化值 (0–1)'


def _normalize(y):
    """将单条曲线归一化到 [0,1]。"""
    lo, hi = float(np.min(y)), float(np.max(y))
    if hi - lo < 1e-12:
        return np.zeros_like(y)
    return (y - lo) / (hi - lo)


def _read_coeffs_from_csv(path):
    """从「批量映射/映射 A→B」导出的 CSV 读取校准系数 (m, c)。

    支持：
      - 批量映射导出：含 `# mean_m <v> mean_c <v>` 行 -> 返回平均值
      - 单组映射导出：含 `# B = m*A + c, m, <v>, c, <v>` 行 -> 返回该组 m, c
    解析失败返回 (None, None)。
    """
    import csv as _csv
    m = c = None
    try:
        with open(path, encoding='utf-8-sig') as f:
            for row in _csv.reader(f):
                cells = [x.strip() for x in row]
                low = [x.lower() for x in cells]
                if any('mean_m' in x or 'mean_c' in x for x in low):
                    for i, x in enumerate(low):
                        if 'mean_m' in x and i + 1 < len(cells):
                            try: m = float(cells[i + 1])
                            except ValueError: pass
                        if 'mean_c' in x and i + 1 < len(cells):
                            try: c = float(cells[i + 1])
                            except ValueError: pass
                    if m is not None and c is not None:
                        return m, c
                joined = ' '.join(low)
                if 'm*a' in joined:
                    for i, x in enumerate(low):
                        if x == 'm' and i + 1 < len(cells):
                            try: m = float(cells[i + 1])
                            except ValueError: pass
                        if x == 'c' and i + 1 < len(cells):
                            try: c = float(cells[i + 1])
                            except ValueError: pass
                    if m is not None and c is not None:
                        return m, c
    except Exception:
        pass
    return m, c


def _sample_key(name):
    """从曲线名提取样品关键字（如 'S1'）。

    返回 (关键字'S1', 编号int, 关键字之后的后缀variant)。无匹配返回 (None, None, None)。
    variant 用于区分同一 S# 的不同变体（如 S1 / S1_raw / S1_absorbance）。
    """
    m = re.search(r'S(\d+)', name)
    if not m:
        return None, None, None
    return m.group(0), int(m.group(1)), name[m.end():]


def _short_name(name, maxlen=22):
    """图例用的短名：有 S# 关键字就返回关键字，否则取尾部。"""
    tok, _, _ = _sample_key(name)
    if tok:
        return tok
    return name[-maxlen:] if len(name) > maxlen else name




class SpectrumApp:
    def __init__(self, root):
        self.root = root
        self.root.title('SpectralCurveTool')
        # 自适应屏幕：尽量高且不超出屏幕（高度上限 960，留出任务栏）
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win_w = min(1500, sw - 60)
        win_h = min(1200, sh - 100)
        self.root.geometry('%dx%d+%d+%d' % (win_w, win_h, max(0, (sw - win_w) // 2), max(0, (sh - win_h) // 3)))
        self.root.minsize(1100, 700)
        self.root.configure(bg=C['background'])

        # 曲线表项：dict(curve, color, visible)
        self.entries = []
        self._tree_ids = []  # Treeview item id 与 entry 一一对应

        apply_theme(self.root)

        # 选项变量
        self._yvar = tk.StringVar(value='raw')        # raw / norm / dual
        self._basevar = tk.StringVar(value='无')      # 差值基准曲线名
        self._diffmode = tk.StringVar(value='相减')    # 相减 / 比值(带下限) / 有界相对偏差
        self._gridvar = tk.BooleanVar(value=True)
        self._legvar = tk.BooleanVar(value=True)

        self._build_ui()
        self._refresh_tree()
        self._redraw()

    # -------------------- UI 构建 --------------------

    def _build_ui(self):
        # 标题栏
        header = ttk.Frame(self.root)
        header.pack(fill='x', padx=15, pady=(12, 6))
        ttk.Label(header, text='近红外光谱对比分析', style='Title.TLabel').pack(side='left')
        dnd_hint = '拖拽可用（已加载 tkinterdnd2）' if HAS_DND else '未安装 tkinterdnd2，请用「添加文件」按钮'
        ttk.Label(header, text=dnd_hint, style='Secondary.TLabel').pack(side='right')

        # 主体：左右分栏
        body = ttk.PanedWindow(self.root, orient='horizontal')
        body.pack(fill='both', expand=True, padx=15, pady=(0, 6))

        self._left = ttk.Frame(body, width=450)
        self._left.pack_propagate(False)
        body.add(self._left, weight=0)

        right = ttk.Frame(body)
        body.add(right, weight=1)

        self._build_left(self._left)
        self._build_right(right)

        # 状态栏
        self._status = ttk.Label(self.root, text='就绪', style='Secondary.TLabel',
                                 anchor='w', background=C['card_translucent'])
        self._status.pack(fill='x', side='bottom', padx=15, pady=(0, 8))

    def _build_left(self, parent):
        # —— 拖拽区 ——
        drop = ttk.LabelFrame(parent, text='数据加载', padding=12)
        drop.pack(fill='x', padx=(0, 10), pady=(0, 10))
        self._drop_label = tk.Label(
            drop,
            text=('将 CSV 文件 / 文件夹\n拖拽到此处\n（或使用下方按钮）'
                  if HAS_DND else '使用下方按钮添加 CSV 文件 / 文件夹'),
            justify='center', bg=C['fill_light'], fg=C['text_secondary'],
            relief='solid', bd=1, height=4,
            font=F['body'])
        self._drop_label.pack(fill='x', pady=(0, 10))
        if HAS_DND:
            self._drop_label.drop_target_register(DND_FILES)
            self._drop_label.dnd_bind('<<Drop>>', self._on_drop)
            # 整窗也可接收拖拽
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self._on_drop)

        btns = ttk.Frame(drop)
        btns.pack(fill='x')
        RoundedButton(btns, '添加文件', command=self._add_files, variant='primary').pack(side='left', padx=(0, 6))
        RoundedButton(btns, '添加文件夹', command=self._add_folder, variant='secondary').pack(side='left', padx=(0, 6))
        RoundedButton(btns, '清空', command=self._clear_all, variant='danger').pack(side='left')

        # —— 曲线列表 ——
        lst = ttk.LabelFrame(parent, text='曲线列表（点击 ☑ 切换显示）', padding=8)
        lst.pack(fill='both', expand=True, padx=(0, 10), pady=(0, 10))

        tree_wrap = ttk.Frame(lst)
        tree_wrap.pack(fill='both', expand=True)
        self._tree = ttk.Treeview(tree_wrap,
                                  columns=('show', 'name', 'ctype', 'points'),
                                  show='headings', height=12)
        self._tree.heading('show', text='显示')
        self._tree.heading('name', text='名称')
        self._tree.heading('ctype', text='类型')
        self._tree.heading('points', text='点数')
        self._tree.column('show', width=50, anchor='center', stretch=False)
        self._tree.column('name', width=240, anchor='w')
        self._tree.column('ctype', width=70, anchor='center', stretch=False)
        self._tree.column('points', width=60, anchor='center', stretch=False)
        vsb = ttk.Scrollbar(tree_wrap, orient='vertical', command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        self._tree.bind('<Button-1>', self._on_tree_click)
        self._tree.bind('<Delete>', lambda e: self._delete_selected())
        self._tree.bind('<Double-1>', lambda e: self._change_color_selected())
        self._tree.bind('<Button-3>', self._on_tree_right_click)

        # 右键菜单
        self._ctx_menu = tk.Menu(self.root, tearoff=0, bg=C['card'], fg=C['text'],
                                 activebackground=C['primary_light'], activeforeground='#FFFFFF',
                                 font=F['body'], borderwidth=1, relief='solid')
        self._ctx_menu.add_command(label='切换显示', command=self._toggle_selected)
        self._ctx_menu.add_command(label='更改颜色…', command=self._change_color_selected)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label='删除选中曲线', command=self._delete_selected)

        # —— 绘图选项 ——
        opt = ttk.LabelFrame(parent, text='绘图选项', padding=10)
        opt.pack(fill='x', padx=(0, 10), pady=(0, 10))

        r1 = ttk.Frame(opt); r1.pack(fill='x', pady=4)
        ttk.Label(r1, text='Y 轴模式：').pack(side='left')
        self._ycombo = ttk.Combobox(r1, textvariable=self._yvar, state='readonly', width=12,
                                    values=('原值', '归一化 0–1', '强度·吸光度双轴'))
        self._ycombo.pack(side='left', padx=6)
        # 映射中文 -> 内部值
        self._y_map = {'原值': 'raw', '归一化 0–1': 'norm', '强度·吸光度双轴': 'dual'}
        self._yvar.set('原值')
        self._ycombo.bind('<<ComboboxSelected>>', lambda e: self._redraw())

        r2 = ttk.Frame(opt); r2.pack(fill='x', pady=4)
        ttk.Label(r2, text='差值基准：').pack(side='left')
        self._base_combo = ttk.Combobox(r2, textvariable=self._basevar, state='readonly', width=24)
        self._base_combo.pack(side='left', padx=6)
        self._base_combo.bind('<<ComboboxSelected>>', lambda e: self._redraw())

        r2b = ttk.Frame(opt); r2b.pack(fill='x', pady=4)
        ttk.Label(r2b, text='差值方式：').pack(side='left')
        self._diff_combo = ttk.Combobox(r2b, textvariable=self._diffmode, state='readonly', width=14,
                                        values=('相减', '比值(带下限)', '有界相对偏差', 'RMSE(原值)'))
        self._diff_combo.pack(side='left', padx=6)
        self._diff_combo.bind('<<ComboboxSelected>>', lambda e: self._redraw())

        r3 = ttk.Frame(opt); r3.pack(fill='x', pady=4)
        ttk.Checkbutton(r3, text='网格', variable=self._gridvar,
                        command=self._redraw).pack(side='left', padx=(0, 16))
        ttk.Checkbutton(r3, text='图例', variable=self._legvar,
                        command=self._redraw).pack(side='left')

        # —— 校准分析 ——
        cal = ttk.LabelFrame(parent, text='校准分析', padding=10)
        cal.pack(fill='x', padx=(0, 10), pady=(0, 10))
        RoundedButton(cal, '映射 / 校准 A→B…', command=self._open_mapping_window,
                      variant='primary').pack(fill='x', pady=(0, 6))
        RoundedButton(cal, '批量映射（求平均）…', command=self._open_batchfit_window,
                      variant='primary').pack(fill='x', pady=(0, 6))
        RoundedButton(cal, '批量校准验证…', command=self._open_batch_window,
                      variant='secondary').pack(fill='x')

        # —— 导出 ——
        ex = ttk.LabelFrame(parent, text='导出', padding=10)
        ex.pack(fill='x', padx=(0, 10))
        rb = ttk.Frame(ex); rb.pack(fill='x')
        RoundedButton(rb, '导出 PNG', command=self._export_png, variant='secondary').pack(side='left', padx=(0, 8))
        RoundedButton(rb, '导出汇总 CSV', command=self._export_summary, variant='secondary').pack(side='left')

    def _build_right(self, parent):
        # 右侧顶部按钮栏
        topbar = ttk.Frame(parent)
        topbar.pack(fill='x', side='top', pady=(0, 4))
        RoundedButton(topbar, '清空显示', command=self._clear_display,
                      variant='secondary').pack(side='right')

        self._fig = Figure(figsize=(8, 5), dpi=100, facecolor=C['background'],
                           constrained_layout=True)
        self._canvas = FigureCanvasTkAgg(self._fig, master=parent)
        self._canvas.get_tk_widget().pack(fill='both', expand=True)
        # 工具栏：缩放/平移/取值/保存
        self._toolbar = NavigationToolbar2Tk(self._canvas, parent, pack_toolbar=False)
        self._toolbar.configure(background=C['background'])
        self._toolbar.update()
        self._toolbar.pack(fill='x')
        for w in self._toolbar.winfo_children():
            try:
                w.configure(background=C['background'], highlightthickness=0)
            except tk.TclError:
                pass

    # -------------------- 数据加载 --------------------

    def _on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        self._add_paths(list(paths))

    def _add_files(self):
        files = filedialog.askopenfilenames(
            title='选择 CSV 文件',
            filetypes=[('CSV 文件', '*.csv'), ('所有文件', '*.*')])
        if files:
            self._add_paths(list(files))

    def _add_folder(self):
        d = filedialog.askdirectory(title='选择文件夹（递归加载 CSV）')
        if d:
            self._add_paths([d])

    def _add_paths(self, paths):
        if not paths:
            return
        curves, errors = load_paths(paths)
        added = 0
        existing = {e['curve'].path for e in self.entries}
        for c in curves:
            if c.path in existing:
                continue
            color = PALETTE[len(self.entries) % len(PALETTE)]
            self.entries.append({'curve': c, 'color': color, 'visible': True})
            existing.add(c.path)
            added += 1
        self._refresh_tree()
        self._redraw()
        msg = f'已加载 {added} 条曲线。'
        if errors:
            msg += f'\n\n跳过 {len(errors)} 个非光谱/无法解析的文件：\n' + '\n'.join(
                f'• {os.path.basename(p)}' for p, _ in errors[:8])
            if len(errors) > 8:
                msg += f'\n…等共 {len(errors)} 个'
        self._set_status(msg.split('\n')[0])
        if added == 0 and not errors:
            messagebox.showinfo('提示', '未发现新的可加载曲线。')
        elif errors:
            messagebox.showinfo('加载完成（部分跳过）', msg)

    def _clear_all(self):
        if not self.entries:
            return
        if messagebox.askyesno('确认', '清空所有曲线？'):
            self.entries.clear()
            self._refresh_tree()
            self._redraw()
            self._set_status('已清空')

    def _clear_display(self):
        """清空右侧画布显示：隐藏全部曲线，保留已加载列表（可重新勾选）。"""
        if not self.entries:
            return
        for e in self.entries:
            e['visible'] = False
        self._refresh_tree()
        self._redraw()
        self._set_status('已清空显示（数据仍保留在列表中）')

    # -------------------- 曲线列表交互 --------------------

    def _refresh_tree(self):
        self._tree.delete(*self._tree.get_children())
        self._tree_ids = []
        for e in self.entries:
            c = e['curve']
            gid = '☑' if e['visible'] else '☐'
            item = self._tree.insert('', 'end', values=(gid, c.name, c.y_type, c.n_points))
            tag = 'row_%d' % len(self._tree_ids)
            self._tree.tag_configure(tag, foreground=e['color'])
            self._tree.item(item, tags=(tag,))
            self._tree_ids.append(item)
        self._refresh_base_combo()

    def _refresh_base_combo(self):
        names = ['无'] + [e['curve'].name for e in self.entries]
        cur = self._basevar.get()
        self._base_combo.configure(values=names)
        if cur not in names:
            self._basevar.set('无')

    def _on_tree_click(self, event):
        region = self._tree.identify('region', event.x, event.y)
        if region != 'cell':
            return
        col = self._tree.identify_column(event.x)
        item = self._tree.identify_row(event.y)
        if not item:
            return
        idx = self._tree_ids.index(item)
        if col == '#1':  # 显示列：切换显隐
            self.entries[idx]['visible'] = not self.entries[idx]['visible']
            self._refresh_tree()
            self._redraw()

    def _selected_index(self):
        sel = self._tree.selection()
        if not sel:
            return None
        return self._tree_ids.index(sel[0])

    def _delete_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        del self.entries[idx]
        self._refresh_tree()
        self._redraw()

    def _change_color_selected(self):
        idx = self._selected_index()
        if idx is None:
            return
        cur = self.entries[idx]['color']
        rgb, hexc = colorchooser.askcolor(color=cur, title='选择曲线颜色')
        if hexc:
            self.entries[idx]['color'] = hexc
            self._refresh_tree()
            self._redraw()

    def _toggle_selected(self):
        """切换选中曲线的显示/隐藏。"""
        idx = self._selected_index()
        if idx is None:
            return
        self.entries[idx]['visible'] = not self.entries[idx]['visible']
        self._refresh_tree()
        self._redraw()

    def _on_tree_right_click(self, event):
        """右键：选中光标所在行并弹出菜单。"""
        item = self._tree.identify_row(event.y)
        if not item:
            return
        self._tree.selection_set(item)
        self._tree.focus(item)
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    # -------------------- 绘图 --------------------

    def _redraw(self):
        self._fig.clear()
        visible = [e for e in self.entries if e['visible']]

        mode = self._y_map.get(self._yvar.get(), 'raw')
        base_name = self._basevar.get()
        base_entry = next((e for e in visible if e['curve'].name == base_name), None) \
            if base_name and base_name != '无' else None
        diff_active = base_entry is not None

        if not visible:
            ax = self._fig.add_subplot(111)
            ax.set_facecolor(C['card'])
            ax.text(0.5, 0.5, '拖入或添加 CSV 文件以显示曲线', transform=ax.transAxes,
                    ha='center', va='center', color=C['text_secondary'], fontsize=12)
            ax.set_xticks([]); ax.set_yticks([])
            for s in ax.spines.values():
                s.set_color(C['border'])
            self._canvas.draw()
            self._set_status('无可见曲线')
            return

        # 顶部主轴 + 可选底部差值子图
        if diff_active:
            ax = self._fig.add_subplot(2, 1, 1)
            axd = self._fig.add_subplot(2, 1, 2, sharex=ax)
        else:
            ax = self._fig.add_subplot(111)
            axd = None

        ax.set_facecolor(C['card'])

        # 是否启用双 Y 轴：仅当双轴模式且可见曲线同时含强度与吸光度
        types = {e['curve'].y_type for e in visible}
        use_dual = (mode == 'dual') and (len(types) > 1)
        ax2 = ax.twinx() if use_dual else None

        def yvals(e):
            y = e['curve'].y
            return _normalize(y) if mode == 'norm' else y

        for e in visible:
            c = e['curve']
            target = ax
            if use_dual and c.y_type == 'absorbance':
                target = ax2
            target.plot(c.x, yvals(e), color=e['color'], linewidth=1.3,
                        label='%s [%s]' % (c.name, c.y_type))

        # 差值子图（参考线/轴名/图例文案随差值方式变化；全部置于 diff_active 内，
        # 避免基准为空时访问 base_entry）
        if diff_active:
            method = self._diffmode.get()
            base_c = base_entry['curve']

            if method == 'RMSE(原值)':
                # 标量相似度：每条曲线 vs 基准的原始吸光度空间 RMSE，底部子图画评分表
                # 始终用原始 Y 值计算（不受 Y 轴模式影响）；0 = 完全一致，单位 = Absorbance
                base_y = base_c.y
                rows = []
                for e in visible:
                    if e is base_entry:
                        continue
                    yn = e['curve'].y
                    bn = np.interp(e['curve'].x, base_c.x, base_y)
                    rows.append((e['curve'].name, float(np.sqrt(np.mean((yn - bn) ** 2)))))
                rows.sort(key=lambda t: t[1])  # RMSE 升序：越像越靠前
                axd.set_facecolor(C['card'])
                axd.axis('off')
                axd.set_title('相对基准「%s」的原始吸光度 RMSE（越小越相似）' % base_name,
                              fontsize=10, color=C['text'], pad=8)
                if rows:
                    cell_text = [[name, '%.5f' % r] for name, r in rows]
                    tbl = axd.table(cellText=cell_text,
                                    colLabels=['曲线', 'RMSE'],
                                    loc='upper center', cellLoc='center', colLoc='center')
                    tbl.auto_set_font_size(False)
                    tbl.set_fontsize(9)
                    tbl.scale(1, 1.35)
                    for k in range(2):  # 表头加深底
                        tbl[(0, k)].set_facecolor(C['card_translucent'])
                else:
                    axd.text(0.5, 0.4, '无其他可见曲线可对比', transform=axd.transAxes,
                             ha='center', va='center', color=C['text_secondary'], fontsize=10)
            else:
                # 相减 / 比值(带下限) / 有界相对偏差：底部子图画差值曲线
                base_eff = _normalize(base_c.y) if mode == 'norm' else base_c.y

                def diff_y(e):
                    y = yvals(e)
                    b = np.interp(e['curve'].x, base_c.x, base_eff)
                    if method == '比值(带下限)':
                        floor = 0.05 * max(float(np.max(np.abs(base_eff))), 1e-12)
                        return y / np.maximum(np.abs(b), floor)
                    if method == '有界相对偏差':
                        denom = np.abs(y) + np.abs(b)
                        with np.errstate(invalid='ignore', divide='ignore'):
                            d = (y - b) / denom
                        return np.where(denom > 1e-12, d, 0.0)   # y=0 & base=0 退化点 -> 0
                    return y - b   # 相减

                if method == '比值(带下限)':
                    ref_line, ylabel, op = 1.0, '比值 (y / base)', '/'
                elif method == '有界相对偏差':
                    ref_line, ylabel, op = 0.0, '相对偏差 [-1, 1]', '相对'
                else:
                    ref_line, ylabel, op = 0.0, '差值', '−'

                axd.set_facecolor(C['card'])
                axd.axhline(ref_line, color=C['text_secondary'], linewidth=0.8, linestyle='-', alpha=0.5)
                for e in visible:
                    if e is base_entry:
                        continue
                    axd.plot(e['curve'].x, diff_y(e), color=e['color'],
                             linewidth=1.1, linestyle='--',
                             label='%s %s %s' % (e['curve'].name, op, base_name))
                axd.set_ylabel(ylabel)
                axd.grid(self._gridvar.get(), alpha=0.3)
                axd.set_xlabel(X_LABEL)
                if self._legvar.get():
                    axd.legend(loc='best', fontsize=8)
                for s in axd.spines.values():
                    s.set_color(C['border'])
        else:
            ax.set_xlabel(X_LABEL)

        # Y 轴标签
        if mode == 'norm':
            ax.set_ylabel(Y_LABEL_NORM)
        elif use_dual:
            ax.set_ylabel(Y_LABEL_INT)
            ax2.set_ylabel(Y_LABEL_ABS)
        else:
            ax.set_ylabel(Y_LABEL_RAW if types == {'intensity'} or types == {'absorbance'}
                          else Y_LABEL_RAW)

        ax.grid(self._gridvar.get(), alpha=0.3)
        for s in ax.spines.values():
            s.set_color(C['border'])
        if ax2:
            for s in ax2.spines.values():
                s.set_color(C['border'])

        if self._legvar.get():
            if ax2:
                h1, l1 = ax.get_legend_handles_labels()
                h2, l2 = ax2.get_legend_handles_labels()
                ax.legend(h1 + h2, l1 + l2, loc='best', fontsize=8)
            else:
                ax.legend(loc='best', fontsize=8)

        self._canvas.draw()

        vis = len(visible)
        xs = np.concatenate([e['curve'].x for e in visible])
        self._set_status('可见 %d 条曲线 | 波长 %.1f–%.1f nm' % (vis, xs.min(), xs.max()))

    # -------------------- 导出 --------------------

    def _export_png(self):
        if not [e for e in self.entries if e['visible']]:
            messagebox.showwarning('提示', '当前无可见曲线。')
            return
        path = filedialog.asksaveasfilename(
            title='导出 PNG', defaultextension='.png',
            filetypes=[('PNG 图片', '*.png')])
        if path:
            self._fig.savefig(path, dpi=150, facecolor=C['background'])
            self._set_status('已导出 PNG：%s' % os.path.basename(path))

    def _export_summary(self):
        visible = [e for e in self.entries if e['visible']]
        if not visible:
            messagebox.showwarning('提示', '当前无可见曲线。')
            return
        path = filedialog.asksaveasfilename(
            title='导出汇总 CSV', defaultextension='.csv',
            filetypes=[('CSV 文件', '*.csv')])
        if not path:
            return
        # 公共波长网格：取所有可见曲线 x 的并集，升序
        grid = np.unique(np.concatenate([e['curve'].x for e in visible]))
        mode = self._y_map.get(self._yvar.get(), 'raw')
        lines = []
        header = ['Wavelength_nm'] + ['%s [%s]' % (e['curve'].name, e['curve'].y_type) for e in visible]
        lines.append(','.join(header))
        cols = []
        for e in visible:
            c = e['curve']
            y = _normalize(c.y) if mode == 'norm' else c.y
            yi = np.interp(grid, c.x, y)
            # 网格点超出该曲线范围 -> 留空
            yi[(grid < c.x.min()) | (grid > c.x.max())] = np.nan
            cols.append(yi)
        for i, wl in enumerate(grid):
            row = ['%.4f' % wl]
            for col in cols:
                row.append('' if np.isnan(col[i]) else ('%.6f' % col[i]))
            lines.append(','.join(row))
        with open(path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines))
        self._set_status('已导出汇总 CSV：%s（%d 点）' % (os.path.basename(path), len(grid)))

    # -------------------- 映射 / 校准 A→B --------------------

    def _open_mapping_window(self):
        """打开独立的 A→B 仿射映射分析窗口（B = m·A + c，在原始值上拟合）。"""
        if len(self.entries) < 2:
            messagebox.showinfo('提示', '至少需要加载 2 条曲线才能做 A→B 映射。')
            return
        if getattr(self, '_map_win', None) is not None and self._map_win.winfo_exists():
            self._map_win.lift(); self._map_win.focus_force(); return

        win = tk.Toplevel(self.root)
        win.title('映射 / 校准 A→B（全局仿射 B = m·A + c）')
        win.geometry('1100x740')
        win.configure(bg=C['background'])
        self._map_win = win
        win.protocol('WM_DELETE_WINDOW', self._close_mapping_window)

        names = [e['curve'].name for e in self.entries]
        self._map_a = tk.StringVar(value=names[0])
        self._map_b = tk.StringVar(value=names[1] if len(names) > 1 else names[0])
        self._map_result = None

        # 顶部：A/B 选择 + 操作按钮
        top = ttk.Frame(win, padding=10)
        top.pack(fill='x')
        cb_w = self._curve_combo_width()
        ttk.Label(top, text='曲线 A：').pack(side='left')
        ttk.Combobox(top, textvariable=self._map_a, values=names, state='readonly',
                     width=cb_w).pack(side='left', padx=(0, 16))
        ttk.Label(top, text='曲线 B：').pack(side='left')
        ttk.Combobox(top, textvariable=self._map_b, values=names, state='readonly',
                     width=cb_w).pack(side='left', padx=(0, 16))
        RoundedButton(top, '计算映射', command=self._compute_mapping, variant='primary').pack(side='left', padx=(0, 8))
        RoundedButton(top, '导出结果', command=self._export_mapping, variant='secondary').pack(side='left')

        # 结果区
        res = ttk.LabelFrame(win, text='拟合结果（在原始值上拟合 B = m·A + c）', padding=10)
        res.pack(fill='x', padx=10, pady=(0, 6))
        self._map_info = ttk.Label(res, text='计算中…', style='Secondary.TLabel', font=F['mono'])
        self._map_info.pack(anchor='w')

        # 画布：3 子图
        cframe = ttk.Frame(win)
        cframe.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self._map_fig = Figure(figsize=(9, 6), dpi=100, facecolor=C['background'], constrained_layout=True)
        self._map_canvas = FigureCanvasTkAgg(self._map_fig, master=cframe)
        self._map_canvas.get_tk_widget().pack(fill='both', expand=True)

        self._compute_mapping()  # 首次自动计算

    def _close_mapping_window(self):
        if getattr(self, '_map_win', None) is not None:
            self._map_win.destroy()
            self._map_win = None

    def _get_curve_by_name(self, name):
        for e in self.entries:
            if e['curve'].name == name:
                return e['curve']
        return None

    def _curve_combo_width(self, minimum=42, maximum=88):
        """按当前已加载曲线名最长者自适应下拉框宽度（字符单位）。"""
        names = [e['curve'].name for e in self.entries] or ['']
        return min(maximum, max(minimum, max(len(n) for n in names) + 2))

    def _compute_smart_pairs(self, src_curve, tgt_curve):
        """以 src/tgt 参考曲线的「文件夹 + 变体后缀」为分组，按 S1–S6 关键字自动配对。"""
        src_dir = os.path.dirname(src_curve.path)
        tgt_dir = os.path.dirname(tgt_curve.path)
        _, _, src_var = _sample_key(src_curve.name)
        _, _, tgt_var = _sample_key(tgt_curve.name)

        def collect(d, var):
            out = {}
            for e in self.entries:
                c = e['curve']
                if os.path.dirname(c.path) != d:
                    continue
                tok, num, after = _sample_key(c.name)
                if tok is None or after != var:
                    continue
                out[num] = c.name  # 同编号取最后一条（极少重复）
            return out

        smap = collect(src_dir, src_var)
        tmap = collect(tgt_dir, tgt_var)
        return [(smap[n], tmap[n]) for n in sorted(set(smap) & set(tmap))]

    def _populate_pairs(self, pairs, pairs_attr, lb_attr):
        setattr(self, pairs_attr, list(pairs))
        lb = getattr(self, lb_attr)
        lb.delete(0, 'end')
        for s, t in pairs:
            lb.insert('end', '%s  →  %s' % (s, t))

    def _fit_affine(self, a, b):
        """在 A、B 波长重叠区间上最小二乘拟合 B ≈ m·A + c；重叠不足返回 None。"""
        x = a.x
        lo = max(float(x.min()), float(b.x.min()))
        hi = min(float(x.max()), float(b.x.max()))
        mask = (x >= lo) & (x <= hi)
        xm = x[mask]
        if xm.size < 2:
            return None
        ya = a.y[mask]
        yb = np.interp(xm, b.x, b.y)
        M = np.vstack([ya, np.ones_like(ya)]).T
        sol = np.linalg.lstsq(M, yb, rcond=None)
        m, c = float(sol[0][0]), float(sol[0][1])
        ap = m * ya + c
        eps = yb - ap
        ss_res = float(np.sum(eps ** 2))
        ss_tot = float(np.sum((yb - yb.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-30 else 0.0
        with np.errstate(invalid='ignore'):
            cc = np.corrcoef(ya, yb)
        r = float(cc[0, 1]) if np.isfinite(cc[0, 1]) else 0.0
        return dict(x=xm, ya=ya, yb=yb, m=m, c=c, ap=ap, eps=eps, r2=r2, r=r,
                    a_name=a.name, b_name=b.name)

    def _compute_mapping(self):
        if getattr(self, '_map_win', None) is None or not self._map_win.winfo_exists():
            return
        a = self._get_curve_by_name(self._map_a.get())
        b = self._get_curve_by_name(self._map_b.get())
        if a is None or b is None:
            self._map_info.configure(text='⚠ 未找到所选曲线')
            return
        res = self._fit_affine(a, b)
        if res is None:
            self._map_info.configure(text='⚠ 两条曲线波长区间无重叠，无法拟合')
            self._map_result = None
            self._draw_mapping_placeholder('波长区间无重叠')
            return
        if a is b:
            self._map_info.configure(text='⚠ A 与 B 是同一条曲线（m≈1, c≈0，无实际意义）')
        else:
            self._map_info.configure(text=self._format_result(res))
        self._map_result = res
        self._draw_mapping(res)

    def _format_result(self, res):
        if res['r2'] > 0.999:
            judge = '映射良好（残差以随机噪声为主）'
        elif res['r2'] > 0.95:
            judge = '部分吻合（残差含系统性结构 = 还有真实差异）'
        else:
            judge = '吻合较差（仿射不足以解释，勿当校准用）'
        return ('B = %.6g · A %s %.6g     |     R² = %.5f     |     Pearson r = %.5f     |     '
                '残差 RMS = %.4g     |     %s') % (
                    res['m'], '+' if res['c'] >= 0 else '−', abs(res['c']),
                    res['r2'], res['r'], float(np.sqrt(np.mean(res['eps'] ** 2))), judge)

    def _draw_mapping_placeholder(self, msg='选择 A、B 后点「计算映射」'):
        self._map_fig.clear()
        ax = self._map_fig.add_subplot(111)
        ax.set_facecolor(C['card'])
        ax.text(0.5, 0.5, msg, transform=ax.transAxes, ha='center', va='center',
                color=C['text_secondary'], fontsize=12)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(C['border'])
        self._map_canvas.draw()

    def _draw_mapping(self, res):
        self._map_fig.clear()
        ax1 = self._map_fig.add_subplot(3, 1, 1)
        ax1.plot(res['x'], res['ya'], color=C['primary'], lw=1.3, label='A: %s' % res['a_name'])
        ax1.plot(res['x'], res['yb'], color=C['danger'], lw=1.3, label='B: %s' % res['b_name'])
        ax1.set_title('① 原始 A vs B', fontsize=10, color=C['text'])
        ax1.set_ylabel('原始值'); ax1.legend(loc='best', fontsize=8)

        ax2 = self._map_fig.add_subplot(3, 1, 2, sharex=ax1)
        ax2.plot(res['x'], res['ap'], color=C['primary'], lw=1.3, ls='--', label="A' = m·A + c")
        ax2.plot(res['x'], res['yb'], color=C['danger'], lw=1.3, label='B')
        ax2.set_title("② 映射后 A′ vs B（应几乎重合）", fontsize=10, color=C['text'])
        ax2.set_ylabel('原始值'); ax2.legend(loc='best', fontsize=8)

        ax3 = self._map_fig.add_subplot(3, 1, 3, sharex=ax1)
        ax3.axhline(0, color=C['text_secondary'], lw=0.8, alpha=0.5)
        ax3.plot(res['x'], res['eps'], color=C['accent'], lw=1.1)
        ax3.set_title('③ 残差 ε = B − A′（系统性结构 = 还有真实差异）', fontsize=10, color=C['text'])
        ax3.set_ylabel('残差 ε'); ax3.set_xlabel('波长 (nm)')

        for ax in (ax1, ax2, ax3):
            ax.grid(True, alpha=0.3); ax.set_facecolor(C['card'])
            for s in ax.spines.values():
                s.set_color(C['border'])
        self._map_canvas.draw()

    def _export_mapping(self):
        res = getattr(self, '_map_result', None)
        if res is None:
            messagebox.showinfo('提示', '请先点「计算映射」生成结果。', parent=self._map_win)
            return
        path = filedialog.asksaveasfilename(
            title='导出映射结果', defaultextension='.csv', parent=self._map_win,
            filetypes=[('CSV 文件', '*.csv')])
        if not path:
            return
        import csv
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['# 映射 A->B (全局仿射)', 'A=' + res['a_name'], 'B=' + res['b_name']])
            w.writerow(['# B = m*A + c', 'm', '%.10g' % res['m'], 'c', '%.10g' % res['c']])
            w.writerow(['# R2', '%.10g' % res['r2'], 'Pearson_r', '%.10g' % res['r'],
                        'residual_RMS', '%.10g' % float(np.sqrt(np.mean(res['eps'] ** 2)))])
            w.writerow(['Wavelength_nm', 'A', 'B', "A'=m*A+c", "eps=B-A'"])
            for i in range(len(res['x'])):
                w.writerow(['%.4f' % res['x'][i], '%.6f' % res['ya'][i], '%.6f' % res['yb'][i],
                            '%.6f' % res['ap'][i], '%.6f' % res['eps'][i]])
        messagebox.showinfo('已导出', '映射结果已保存：\n' + os.path.basename(path), parent=self._map_win)

    # -------------------- 批量校准验证 --------------------

    def _open_batch_window(self):
        """把 (m,c) 套用到一组曲线，与另一组逐配对对比，验证校准系数好坏。"""
        if len(self.entries) < 2:
            messagebox.showinfo('提示', '至少需要 2 条曲线。')
            return
        if getattr(self, '_batch_win', None) is not None and self._batch_win.winfo_exists():
            self._batch_win.lift(); self._batch_win.focus_force(); return

        win = tk.Toplevel(self.root)
        win.title('批量校准验证（把 m·A + c 套到一组，与另一组对比）')
        win.geometry('1180x860')
        win.configure(bg=C['background'])
        self._batch_win = win
        win.protocol('WM_DELETE_WINDOW', self._close_batch_window)

        names = [e['curve'].name for e in self.entries]
        self._batch_pairs = []  # 显式配对列表：[(源曲线名, 目标曲线名), ...]

        # 系数区
        ctop = ttk.LabelFrame(win, text='校准系数  B = m·A + c', padding=10)
        ctop.pack(fill='x', padx=10, pady=10)
        self._batch_m = tk.StringVar(value='1')
        self._batch_c = tk.StringVar(value='0')
        er = ttk.Frame(ctop); er.pack(fill='x', pady=(0, 8))
        ttk.Label(er, text='m：').pack(side='left')
        ttk.Entry(er, textvariable=self._batch_m, width=16).pack(side='left', padx=(0, 16))
        ttk.Label(er, text='c：').pack(side='left')
        ttk.Entry(er, textvariable=self._batch_c, width=16).pack(side='left')
        br = ttk.Frame(ctop); br.pack(fill='x')
        RoundedButton(br, '使用上次 A→B 结果', command=self._batch_use_last, variant='secondary').pack(side='left', padx=(0, 8))
        RoundedButton(br, '使用批量映射平均', command=self._batch_use_bf_avg, variant='secondary').pack(side='left', padx=(0, 8))
        RoundedButton(br, '从 CSV 导入系数', command=self._batch_import_csv, variant='secondary').pack(side='left')

        # 配对构建区（显式：源 + 目标 → 添加配对）
        cb_w = self._curve_combo_width()
        pb = ttk.LabelFrame(win, text='构建配对（源曲线 套用 m·A+c，与 目标曲线 对比）', padding=10)
        pb.pack(fill='x', padx=10, pady=(0, 8))
        row1 = ttk.Frame(pb); row1.pack(fill='x', pady=4)
        ttk.Label(row1, text='源曲线：').pack(side='left')
        self._batch_src_var = tk.StringVar(value=names[0])
        ttk.Combobox(row1, textvariable=self._batch_src_var, values=names, state='readonly',
                     width=cb_w).pack(side='left', padx=(6, 14))
        ttk.Label(row1, text='目标曲线：').pack(side='left')
        self._batch_tgt_var = tk.StringVar(value=names[1] if len(names) > 1 else names[0])
        ttk.Combobox(row1, textvariable=self._batch_tgt_var, values=names, state='readonly',
                     width=cb_w).pack(side='left', padx=(6, 14))
        RoundedButton(row1, '添加配对', command=self._batch_add_pair, variant='primary').pack(side='left', padx=(0, 8))
        RoundedButton(row1, '智能配对 S1–S6', command=self._batch_smart_pair, variant='secondary').pack(side='left')

        row2 = ttk.Frame(pb); row2.pack(fill='x')
        self._batch_pairs_lb = tk.Listbox(row2, height=6, exportselection=False, bg=C['card'],
                                          fg=C['text'], selectbackground=C['primary_light'],
                                          selectforeground='#FFFFFF', activestyle='none',
                                          borderwidth=1, highlightthickness=0, relief='solid', font=F['body'])
        self._batch_pairs_lb.pack(side='left', fill='both', expand=True)
        rb2 = ttk.Frame(row2); rb2.pack(side='left', fill='y', padx=(8, 0))
        RoundedButton(rb2, '移除选中', command=self._batch_remove_pair, variant='secondary').pack(fill='x', pady=(0, 6))
        RoundedButton(rb2, '清空配对', command=self._batch_clear_pairs, variant='danger').pack(fill='x')

        # 计算按钮
        btns = ttk.Frame(win); btns.pack(fill='x', padx=10, pady=(0, 6))
        RoundedButton(btns, '计算', command=self._batch_compute, variant='primary').pack(side='left')

        # 结果表
        rf = ttk.LabelFrame(win, text='逐配对结果', padding=8)
        rf.pack(fill='x', padx=10, pady=(0, 8))
        self._batch_tree = ttk.Treeview(rf, columns=('pair', 'rms', 'r2', 'r'), show='headings', height=7)
        for col, txt, w, anc in (('pair', '配对 (校准源 → 目标)', 340, 'w'),
                                 ('rms', '残差RMS', 110, 'center'),
                                 ('r2', 'R²', 100, 'center'),
                                 ('r', 'Pearson r', 100, 'center')):
            self._batch_tree.heading(col, text=txt)
            self._batch_tree.column(col, width=w, anchor=anc)
        self._batch_tree.pack(fill='x')

        # 图表区：两页 —— 残差叠加 / 还原曲线对比
        nb = ttk.Notebook(win)
        nb.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        t1 = ttk.Frame(nb); nb.add(t1, text='残差叠加')
        self._batch_fig = Figure(figsize=(9, 3.4), dpi=100, facecolor=C['background'], constrained_layout=True)
        self._batch_canvas = FigureCanvasTkAgg(self._batch_fig, master=t1)
        self._batch_canvas.get_tk_widget().pack(fill='both', expand=True)

        t2 = ttk.Frame(nb); nb.add(t2, text='还原曲线对比')
        t2bar = ttk.Frame(t2); t2bar.pack(fill='x', pady=(4, 4))
        RoundedButton(t2bar, '显示选中配对（配对列表可多选；空选=全部）',
                      command=self._batch_draw_restore, variant='secondary').pack(side='left')
        self._batch_restore_fig = Figure(figsize=(9, 4.6), dpi=100, facecolor=C['background'], constrained_layout=True)
        self._batch_restore_canvas = FigureCanvasTkAgg(self._batch_restore_fig, master=t2)
        self._batch_restore_canvas.get_tk_widget().pack(fill='both', expand=True)

        self._batch_draw_placeholder('选择源组/目标组后点「计算」')
        self._batch_restore_placeholder('点「计算」后，在配对列表选中若干（可多选）再点上方按钮查看还原曲线')

        if getattr(self, '_map_result', None):  # 预填上次结果
            self._batch_use_last()

    def _close_batch_window(self):
        if getattr(self, '_batch_win', None) is not None:
            self._batch_win.destroy()
            self._batch_win = None

    def _batch_use_last(self):
        r = getattr(self, '_map_result', None)
        if r is None:
            messagebox.showinfo('提示', '尚无 A→B 拟合结果，请先在「映射/校准 A→B」窗口计算一次。',
                                parent=self._batch_win)
            return
        self._batch_m.set('%.10g' % r['m'])
        self._batch_c.set('%.10g' % r['c'])

    def _batch_use_bf_avg(self):
        """直接套用本次会话里「批量映射（求平均）」的平均系数。"""
        avg = getattr(self, '_bf_avg', None)
        if avg is None:
            messagebox.showinfo('提示', '尚无「批量映射」的平均结果，请先在「批量映射（求平均）」窗口计算一次。',
                                parent=self._batch_win)
            return
        m_mean, c_mean = avg[0], avg[1]
        self._batch_m.set('%.10g' % m_mean)
        self._batch_c.set('%.10g' % c_mean)

    def _batch_import_csv(self):
        """从「批量映射/映射 A→B」导出的 CSV 导入校准系数 m、c（支持平均值）。"""
        path = filedialog.askopenfilename(
            title='选择批量映射/映射结果导出的 CSV', parent=self._batch_win,
            filetypes=[('CSV 文件', '*.csv')])
        if not path:
            return
        m, c = _read_coeffs_from_csv(path)
        if m is None or c is None:
            messagebox.showerror('错误',
                                 '未能从该 CSV 解析出 m、c。请选择「批量映射」或「映射 A→B」导出的 CSV。',
                                 parent=self._batch_win)
            return
        self._batch_m.set('%.10g' % m)
        self._batch_c.set('%.10g' % c)
        messagebox.showinfo('已导入', '从 CSV 读入：m = %.6g，c = %.6g' % (m, c), parent=self._batch_win)

    def _batch_add_pair(self):
        s, t = self._batch_src_var.get(), self._batch_tgt_var.get()
        if not s or not t:
            return
        self._batch_pairs.append((s, t))
        self._batch_pairs_lb.insert('end', '%s  →  %s' % (s, t))

    def _batch_remove_pair(self):
        sel = self._batch_pairs_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self._batch_pairs_lb.delete(idx)
        del self._batch_pairs[idx]

    def _batch_clear_pairs(self):
        self._batch_pairs_lb.delete(0, 'end')
        self._batch_pairs = []

    def _batch_smart_pair(self):
        """按当前所选源/目标参考曲线的文件夹+变体，自动生成 S1–S6 配对。"""
        cs = self._get_curve_by_name(self._batch_src_var.get())
        ct = self._get_curve_by_name(self._batch_tgt_var.get())
        if cs is None or ct is None:
            messagebox.showinfo('提示', '请先在源/目标下拉框各选一条曲线作为分组参考。', parent=self._batch_win); return
        pairs = self._compute_smart_pairs(cs, ct)
        if not pairs:
            messagebox.showinfo('提示', '未能按 S1–S6 自动配对。请确认两条参考曲线分属不同文件夹且含 S# 关键字。',
                                parent=self._batch_win); return
        self._populate_pairs(pairs, '_batch_pairs', '_batch_pairs_lb')
        messagebox.showinfo('智能配对', '已按 S1–S6 生成 %d 组配对。' % len(pairs), parent=self._batch_win)

    def _batch_pair_residual(self, a, b, m, c):
        """对 a 套用 m·a+c 后与 b（插值到重叠区）比，返回残差统计；无重叠返回 None。"""
        x = a.x
        lo = max(float(x.min()), float(b.x.min()))
        hi = min(float(x.max()), float(b.x.max()))
        mask = (x >= lo) & (x <= hi)
        xm = x[mask]
        if xm.size < 2:
            return None
        ya = a.y[mask]
        a_cal = m * ya + c
        b_v = np.interp(xm, b.x, b.y)
        eps = b_v - a_cal
        sst = float(np.sum((b_v - b_v.mean()) ** 2))
        r2 = 1.0 - float(np.sum(eps ** 2)) / sst if sst > 1e-30 else 0.0
        with np.errstate(invalid='ignore'):
            cc = np.corrcoef(a_cal, b_v)
        r = float(cc[0, 1]) if np.isfinite(cc[0, 1]) else 0.0
        return dict(x=xm, ya=ya, yb=b_v, acal=a_cal, eps=eps,
                    rms=float(np.sqrt(np.mean(eps ** 2))), r2=r2, r=r)

    def _batch_compute(self):
        if getattr(self, '_batch_win', None) is None or not self._batch_win.winfo_exists():
            return
        if not self._batch_pairs:
            messagebox.showinfo('提示', '请先用「添加配对」至少构建 1 组对比。', parent=self._batch_win)
            return
        try:
            m = float(self._batch_m.get()); c = float(self._batch_c.get())
        except ValueError:
            messagebox.showerror('错误', 'm、c 必须是数字。', parent=self._batch_win); return

        pairs, rows, eps_list = [], [], []
        for s, t in self._batch_pairs:
            a = self._get_curve_by_name(s); b = self._get_curve_by_name(t)
            if a is None or b is None:
                messagebox.showinfo('提示', '找不到曲线：%s / %s' % (s, t), parent=self._batch_win); return
            res = self._batch_pair_residual(a, b, m, c)
            if res is None:
                messagebox.showinfo('提示', '曲线 %s 与 %s 波长区间无重叠。' % (s, t),
                                    parent=self._batch_win); return
            pairs.append((s, t)); rows.append(res); eps_list.append(res)

        self._batch_tree.delete(*self._batch_tree.get_children())
        rms_vals = []
        for (s, t), res in zip(pairs, rows):
            self._batch_tree.insert('', 'end', values=(
                '%s → %s' % (s, t), '%.4f' % res['rms'], '%.5f' % res['r2'], '%.5f' % res['r']))
            rms_vals.append(res['rms'])
        mean_rms = float(np.mean(rms_vals)); max_rms = float(np.max(rms_vals))
        self._batch_tree.insert('', 'end', values=(
            '汇总：平均 / 最大 RMS', '%.4f / %.4f' % (mean_rms, max_rms), '', ''))

        self._batch_last = [(s, t, res) for (s, t), res in zip(pairs, rows)]  # 供还原曲线视图使用
        self._batch_draw_residuals(eps_list, pairs, mean_rms)
        self._batch_draw_restore()  # 同步刷新还原曲线视图

    def _batch_draw_residuals(self, eps_list, pairs, mean_rms):
        self._batch_fig.clear()
        ax = self._batch_fig.add_subplot(111)
        ax.axhline(0, color=C['text_secondary'], lw=0.8, alpha=0.5)
        for i, res in enumerate(eps_list):
            col = PALETTE[i % len(PALETTE)]
            a, b = pairs[i]
            ax.plot(res['x'], res['eps'], color=col, lw=1.0, alpha=0.85, label='%s vs %s' % (a, b))
        ax.set_xlabel('波长 (nm)'); ax.set_ylabel('残差 (目标 − 校准源)')
        ax.set_title('各配对残差叠加（平均 RMS = %.4f，越小 = 校准越好）' % mean_rms,
                     fontsize=10, color=C['text'])
        ax.grid(True, alpha=0.3); ax.set_facecolor(C['card'])
        ax.legend(loc='best', fontsize=7, ncol=2)
        for s in ax.spines.values():
            s.set_color(C['border'])
        self._batch_canvas.draw()

    def _batch_draw_placeholder(self, msg):
        self._batch_fig.clear()
        ax = self._batch_fig.add_subplot(111); ax.set_facecolor(C['card'])
        ax.text(0.5, 0.5, msg, transform=ax.transAxes, ha='center', va='center',
                color=C['text_secondary'], fontsize=12)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(C['border'])
        self._batch_canvas.draw()

    def _batch_restore_placeholder(self, msg):
        self._batch_restore_fig.clear()
        ax = self._batch_restore_fig.add_subplot(111); ax.set_facecolor(C['card'])
        ax.text(0.5, 0.5, msg, transform=ax.transAxes, ha='center', va='center',
                color=C['text_secondary'], fontsize=12)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(C['border'])
        self._batch_restore_canvas.draw()

    def _batch_draw_restore(self):
        """还原曲线对比：源 A（黑虚线）/ 校准 A′=mA+c（加粗实线）/ 目标 B（加粗实线）。
        在配对列表里选中若干（可多选）决定显示哪些；空选则显示全部。"""
        last = getattr(self, '_batch_last', None)
        if not last:
            self._batch_restore_placeholder('请先点「计算」生成结果')
            return
        sel = self._batch_pairs_lb.curselection()
        idxs = sorted(sel) if sel else list(range(len(last)))
        show = [last[i] for i in idxs if 0 <= i < len(last)]
        if not show:
            self._batch_restore_placeholder('无配对可显示')
            return

        self._batch_restore_fig.clear()
        ax = self._batch_restore_fig.add_subplot(111)
        ax.set_facecolor(C['card'])
        for k, (s, t, res) in enumerate(show):
            col_a = PALETTE[(2 * k) % len(PALETTE)]
            col_b = PALETTE[(2 * k + 1) % len(PALETTE)]
            ax.plot(res['x'], res['ya'], color='black', lw=1.0, ls='--', alpha=0.75,
                    label='源 A（黑虚线）' if k == 0 else None)
            ax.plot(res['x'], res['acal'], color=col_a, lw=2.4,
                    label="A′=mA+c：%s" % _short_name(s))
            ax.plot(res['x'], res['yb'], color=col_b, lw=2.4,
                    label='目标 B：%s' % _short_name(t))
        ax.set_xlabel('波长 (nm)'); ax.set_ylabel('值')
        ax.set_title('还原曲线对比（校准后 A′ 应与目标 B 重合）', fontsize=10, color=C['text'])
        ax.grid(True, alpha=0.3)
        ax.legend(loc='best', fontsize=7)
        for s2 in ax.spines.values():
            s2.set_color(C['border'])
        self._batch_restore_canvas.draw()

    # -------------------- 批量映射 / 求平均校准系数 --------------------

    def _open_batchfit_window(self):
        """对多组配对各自拟合 B=m·A+c，取 m、c 平均作为整组映射；每组残差各画一张子图。"""
        if len(self.entries) < 2:
            messagebox.showinfo('提示', '至少需要 2 条曲线。')
            return
        if getattr(self, '_bf_win', None) is not None and self._bf_win.winfo_exists():
            self._bf_win.lift(); self._bf_win.focus_force(); return

        win = tk.Toplevel(self.root)
        win.title('批量映射 / 求平均校准系数（每组拟合 B=m·A+c，取平均）')
        win.geometry('1220x920')
        win.configure(bg=C['background'])
        self._bf_win = win
        win.protocol('WM_DELETE_WINDOW', self._close_batchfit_window)

        names = [e['curve'].name for e in self.entries]
        self._bf_pairs = []
        self._bf_fits = None
        cb_w = self._curve_combo_width()

        info = ttk.LabelFrame(win, text='说明', padding=8)
        info.pack(fill='x', padx=10, pady=10)
        ttk.Label(info, text='为每个配对拟合 B = m·A + c 得到每组系数；最后取 m、c 的平均值作为「A 组 → B 组」整体映射。'
                             '每个配对的残差单独画一张子图，便于横向比较。',
                  style='Secondary.TLabel').pack(anchor='w')

        # 配对构建
        pb = ttk.LabelFrame(win, text='构建配对（源 A → 目标 B）', padding=10)
        pb.pack(fill='x', padx=10, pady=(0, 8))
        row1 = ttk.Frame(pb); row1.pack(fill='x', pady=4)
        ttk.Label(row1, text='源曲线 A：').pack(side='left')
        self._bf_src_var = tk.StringVar(value=names[0])
        ttk.Combobox(row1, textvariable=self._bf_src_var, values=names, state='readonly',
                     width=cb_w).pack(side='left', padx=(6, 14))
        ttk.Label(row1, text='目标曲线 B：').pack(side='left')
        self._bf_tgt_var = tk.StringVar(value=names[1] if len(names) > 1 else names[0])
        ttk.Combobox(row1, textvariable=self._bf_tgt_var, values=names, state='readonly',
                     width=cb_w).pack(side='left', padx=(6, 14))
        RoundedButton(row1, '添加配对', command=self._bf_add_pair, variant='primary').pack(side='left', padx=(0, 8))
        RoundedButton(row1, '智能配对 S1–S6', command=self._bf_smart_pair, variant='secondary').pack(side='left')
        row2 = ttk.Frame(pb); row2.pack(fill='x')
        self._bf_pairs_lb = tk.Listbox(row2, height=6, exportselection=False, bg=C['card'],
                                       fg=C['text'], selectbackground=C['primary_light'],
                                       selectforeground='#FFFFFF', activestyle='none',
                                       borderwidth=1, highlightthickness=0, relief='solid', font=F['body'])
        self._bf_pairs_lb.pack(side='left', fill='both', expand=True)
        rb2 = ttk.Frame(row2); rb2.pack(side='left', fill='y', padx=(8, 0))
        RoundedButton(rb2, '移除选中', command=self._bf_remove_pair, variant='secondary').pack(fill='x', pady=(0, 6))
        RoundedButton(rb2, '清空配对', command=self._bf_clear_pairs, variant='danger').pack(fill='x')

        act = ttk.Frame(win); act.pack(fill='x', padx=10, pady=(0, 6))
        ttk.Label(act, text='聚合方式：').pack(side='left')
        self._bf_agg_var = tk.StringVar(value='期望(残差倒数加权)')
        ttk.Combobox(act, textvariable=self._bf_agg_var, state='readonly', width=18,
                     values=('期望(残差倒数加权)', '平均(算术)', '中位数')).pack(side='left', padx=(6, 16))
        RoundedButton(act, '计算', command=self._bf_compute, variant='primary').pack(side='left')
        RoundedButton(act, '导出结果', command=self._bf_export, variant='secondary').pack(side='left', padx=10)

        # 结果表
        rf = ttk.LabelFrame(win, text='逐配对拟合结果 + 平均', padding=8)
        rf.pack(fill='x', padx=10, pady=(0, 8))
        self._bf_tree = ttk.Treeview(rf, columns=('pair', 'm', 'c', 'r2', 'r'), show='headings', height=7)
        for col, txt, wv, anc in (('pair', '配对 (A → B)', 400, 'w'),
                                  ('m', 'm', 95, 'center'),
                                  ('c', 'c', 95, 'center'),
                                  ('r2', 'R²', 95, 'center'),
                                  ('r', 'Pearson r', 95, 'center')):
            self._bf_tree.heading(col, text=txt)
            self._bf_tree.column(col, width=wv, anchor=anc)
        self._bf_tree.pack(fill='x')

        # 子图网格
        pf = ttk.Frame(win); pf.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self._bf_fig = Figure(figsize=(10, 5), dpi=100, facecolor=C['background'], constrained_layout=True)
        self._bf_canvas = FigureCanvasTkAgg(self._bf_fig, master=pf)
        self._bf_canvas.get_tk_widget().pack(fill='both', expand=True)
        self._bf_draw_placeholder('用上方构建配对后点「计算」（每个配对一张子图）')

    def _close_batchfit_window(self):
        if getattr(self, '_bf_win', None) is not None:
            self._bf_win.destroy()
            self._bf_win = None

    def _bf_add_pair(self):
        s, t = self._bf_src_var.get(), self._bf_tgt_var.get()
        if not s or not t:
            return
        self._bf_pairs.append((s, t))
        self._bf_pairs_lb.insert('end', '%s  →  %s' % (s, t))

    def _bf_remove_pair(self):
        sel = self._bf_pairs_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self._bf_pairs_lb.delete(idx)
        del self._bf_pairs[idx]

    def _bf_clear_pairs(self):
        self._bf_pairs_lb.delete(0, 'end')
        self._bf_pairs = []

    def _bf_smart_pair(self):
        """按当前所选源/目标参考曲线的文件夹+变体，自动生成 S1–S6 配对。"""
        cs = self._get_curve_by_name(self._bf_src_var.get())
        ct = self._get_curve_by_name(self._bf_tgt_var.get())
        if cs is None or ct is None:
            messagebox.showinfo('提示', '请先在源/目标下拉框各选一条曲线作为分组参考。', parent=self._bf_win); return
        pairs = self._compute_smart_pairs(cs, ct)
        if not pairs:
            messagebox.showinfo('提示', '未能按 S1–S6 自动配对。请确认两条参考曲线分属不同文件夹且含 S# 关键字。',
                                parent=self._bf_win); return
        self._populate_pairs(pairs, '_bf_pairs', '_bf_pairs_lb')
        messagebox.showinfo('智能配对', '已按 S1–S6 生成 %d 组配对。' % len(pairs), parent=self._bf_win)

    def _aggregate(self, vals, rms_list, mode):
        """按指定方式聚合系数。返回 (聚合值, 离散度)。

        - 平均(算术)：mean / std
        - 期望(残差倒数加权)：w=1/RMS² 的加权期望 / 加权标准差（高偏差组权重被压低）
        - 中位数：median / 标准化 MAD（1.4826·median|x-中位|，抗离群）
        """
        v = np.asarray(vals, dtype=float)
        if mode == '中位数':
            agg = float(np.median(v))
            spread = 1.4826 * float(np.median(np.abs(v - agg)))
            return agg, spread
        if mode == '期望(残差倒数加权)':
            rms = np.asarray(rms_list, dtype=float)
            w = 1.0 / (rms ** 2 + 1e-12)
            agg = float(np.sum(w * v) / np.sum(w))
            spread = float(np.sqrt(np.sum(w * (v - agg) ** 2) / np.sum(w)))
            return agg, spread
        agg = float(np.mean(v))
        spread = float(np.std(v))
        return agg, spread

    def _bf_compute(self):
        if getattr(self, '_bf_win', None) is None or not self._bf_win.winfo_exists():
            return
        if not self._bf_pairs:
            messagebox.showinfo('提示', '请先用「添加配对」至少构建 1 组。', parent=self._bf_win); return
        fits = []
        for s, t in self._bf_pairs:
            a = self._get_curve_by_name(s); b = self._get_curve_by_name(t)
            if a is None or b is None:
                messagebox.showinfo('提示', '找不到曲线：%s / %s' % (s, t), parent=self._bf_win); return
            res = self._fit_affine(a, b)
            if res is None:
                messagebox.showinfo('提示', '曲线 %s 与 %s 波长区间无重叠。' % (s, t), parent=self._bf_win); return
            fits.append(res)
        self._bf_fits = fits

        self._bf_tree.delete(*self._bf_tree.get_children())
        ms, cs, rms = [], [], []
        for r in fits:
            self._bf_tree.insert('', 'end', values=(
                '%s → %s' % (r['a_name'], r['b_name']), '%.6g' % r['m'], '%.6g' % r['c'],
                '%.5f' % r['r2'], '%.5f' % r['r']))
            ms.append(r['m']); cs.append(r['c'])
            rms.append(float(np.sqrt(np.mean(r['eps'] ** 2))))

        mode = self._bf_agg_var.get()
        m_agg, m_spread = self._aggregate(ms, rms, mode)
        c_agg, c_spread = self._aggregate(cs, rms, mode)
        self._bf_avg = (m_agg, c_agg, m_spread, c_spread, mode)
        agg_label = {'平均(算术)': '平均（算术，A 组 → B 组 整体映射）',
                     '期望(残差倒数加权)': '期望（残差倒数加权，整体映射；残差越小权重越大）',
                     '中位数': '中位数（稳健，抗离群）'}[mode]
        spread_label = {'平均(算术)': '标准差（一致性）',
                        '期望(残差倒数加权)': '加权离散度（越小越一致）',
                        '中位数': '稳健离散度（MAD）'}[mode]
        self._bf_tree.insert('', 'end', values=(agg_label, '%.6g' % m_agg, '%.6g' % c_agg, '', ''))
        self._bf_tree.insert('', 'end', values=(spread_label, '%.4g' % m_spread, '%.4g' % c_spread, '', ''))

        self._bf_draw_grid(fits)

    def _bf_draw_grid(self, fits):
        n = len(fits)
        ncols = min(3, n)
        nrows = (n + ncols - 1) // ncols
        self._bf_fig.clear()
        for i, r in enumerate(fits):
            ax = self._bf_fig.add_subplot(nrows, ncols, i + 1)
            ax.axhline(0, color=C['text_secondary'], lw=0.8, alpha=0.5)
            ax.plot(r['x'], r['eps'], color=PALETTE[i % len(PALETTE)], lw=1.0)
            short_a = r['a_name'][-22:] if len(r['a_name']) > 22 else r['a_name']
            short_b = r['b_name'][-22:] if len(r['b_name']) > 22 else r['b_name']
            ax.set_title('%s→%s  m=%.4g c=%.3g' % (short_a, short_b, r['m'], r['c']),
                         fontsize=8, color=C['text'])
            ax.set_ylabel('残差 ε', fontsize=8)
            if i >= (nrows - 1) * ncols:
                ax.set_xlabel('波长 (nm)', fontsize=8)
            ax.grid(True, alpha=0.3); ax.set_facecolor(C['card'])
            ax.tick_params(labelsize=7)
            for s in ax.spines.values():
                s.set_color(C['border'])
        self._bf_canvas.draw()

    def _bf_draw_placeholder(self, msg):
        self._bf_fig.clear()
        ax = self._bf_fig.add_subplot(111); ax.set_facecolor(C['card'])
        ax.text(0.5, 0.5, msg, transform=ax.transAxes, ha='center', va='center',
                color=C['text_secondary'], fontsize=12)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_color(C['border'])
        self._bf_canvas.draw()

    def _bf_export(self):
        fits = getattr(self, '_bf_fits', None)
        if not fits:
            messagebox.showinfo('提示', '请先点「计算」生成结果。', parent=self._bf_win); return
        path = filedialog.asksaveasfilename(
            title='导出批量映射结果', defaultextension='.csv', parent=self._bf_win,
            filetypes=[('CSV 文件', '*.csv')])
        if not path:
            return
        m_agg, c_agg, m_spread, c_spread, mode = self._bf_avg
        import csv
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f)
            w.writerow(['# 批量映射 A组->B组 (聚合方式: %s)' % mode])
            w.writerow(['# mean_m', '%.10g' % m_agg, 'mean_c', '%.10g' % c_agg])
            w.writerow(['# spread_m', '%.10g' % m_spread, 'spread_c', '%.10g' % c_spread])
            w.writerow(['source_A', 'target_B', 'm', 'c', 'R2', 'Pearson_r', 'residual_RMS'])
            for r in fits:
                w.writerow([r['a_name'], r['b_name'], '%.10g' % r['m'], '%.10g' % r['c'],
                            '%.10g' % r['r2'], '%.10g' % r['r'],
                            '%.10g' % float(np.sqrt(np.mean(r['eps'] ** 2)))])
        messagebox.showinfo('已导出', '%s\nm=%.6g, c=%.6g\n已保存：%s' % (mode, m_agg, c_agg, os.path.basename(path)),
                            parent=self._bf_win)

    # -------------------- 杂项 --------------------

    def _set_status(self, text):
        self._status.configure(text=text)


def launch():
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = SpectrumApp(root)
    root.mainloop()


if __name__ == '__main__':
    launch()
