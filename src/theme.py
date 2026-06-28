# -*- coding: utf-8 -*-
"""
Professional Scientific Theme —— 科研工具主题风格规范。

移植自 Read_Macleod/Style/Professional_Scientific_Theme.md 第 7 节可复用常量，
并补充完整的 ttk Style 配置与圆角按钮组件，供本项目的 tkinter/ttk 应用统一调用。
"""

import tkinter as tk
from tkinter import ttk


# ========== 字体检测 ==========

def _detect_font():
    """运行时按优先级选择字体族，确保跨平台可用性。"""
    import tkinter.font as tkfont
    root = tk.Tk()
    root.withdraw()
    available = tkfont.families(root)
    root.destroy()
    for candidate in ['Segoe UI Variable', 'Segoe UI', 'Helvetica Neue', 'Microsoft YaHei UI']:
        if candidate in available:
            return candidate
    return 'Microsoft YaHei'


_BODY_FONT = _detect_font()


# ========== 色彩体系 ==========

THEME_COLORS = {
    'background':           '#F8FAFC',
    'card':                 '#FFFFFF',
    'card_translucent':     '#F1F5F9',
    'primary':              '#1E3A5F',
    'primary_dark':         '#152C4A',
    'primary_light':        '#2563EB',
    'accent':               '#059669',
    'accent_dark':          '#047857',
    'text':                 '#0F172A',
    'text_secondary':       '#64748B',
    'separator':            '#E2E8F0',
    'border':               '#E4E7EB',
    'fill':                 '#E2E8F0',
    'fill_light':           '#F1F5F9',
    'danger':               '#DC2626',
    'danger_dark':          '#B91C1C',
    'success':              '#059669',
    'button_secondary':     '#E2E8F0',
    'button_secondary_text':'#334155',
    'hover':                '#EFF6FF',
    'focus_ring':           '#2563EB',
}


# ========== 字体阶梯 ==========

THEME_FONTS = {
    'title':        (_BODY_FONT, 16, 'bold'),
    'section':      (_BODY_FONT, 13, 'bold'),
    'tab':          (_BODY_FONT, 11),
    'body':         (_BODY_FONT, 10),
    'button':       (_BODY_FONT, 12, 'bold'),
    'button_small': (_BODY_FONT, 10, 'bold'),
    'label_bold':   (_BODY_FONT, 10, 'bold'),
    'accent_value': (_BODY_FONT, 11, 'bold'),
    'mono':         ('Cascadia Code', 10) if 'Cascadia Code' in _BODY_FONT else ('Consolas', 10),
}

THEME_BUTTON_CFG = {
    'bd': 0, 'relief': 'flat', 'cursor': 'hand2', 'activeforeground': '#ffffff',
}


# ========== 颜色工具 ==========

def _hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*[max(0, min(255, int(round(v)))) for v in rgb])


def lighten(hex_color, factor=0.08):
    """提亮颜色：factor>0 提亮，<0 压暗。"""
    r, g, b = _hex_to_rgb(hex_color)
    if factor >= 0:
        rgb = (r + (255 - r) * factor, g + (255 - g) * factor, b + (255 - b) * factor)
    else:
        f = 1 + factor
        rgb = (r * f, g * f, b * f)
    return _rgb_to_hex(rgb)


# ========== 圆角按钮 (RoundedButton) ==========

class RoundedButton(tk.Canvas):
    """基于 Canvas 绘制的圆角按钮，替代原生 tk.Button/ttk.Button。

    variant: 'primary'(翠绿) / 'secondary'(灰) / 'danger'(红)
    """

    def __init__(self, parent, text, command=None, variant='primary',
                 font=None, padx=16, pady=8, radius=8, width=None, **kw):

        if variant == 'primary':
            self._bg = THEME_COLORS['accent']
            self._active = THEME_COLORS['accent_dark']
            self._fg = '#FFFFFF'
            font = font or THEME_FONTS['button']
        elif variant == 'danger':
            self._bg = THEME_COLORS['danger']
            self._active = THEME_COLORS['danger_dark']
            self._fg = '#FFFFFF'
            font = font or THEME_FONTS['button_small']
        else:  # secondary
            self._bg = THEME_COLORS['button_secondary']
            self._active = THEME_COLORS['fill']
            self._fg = THEME_COLORS['button_secondary_text']
            font = font or THEME_FONTS['button_small']

        self._command = command
        self._text = text
        self._padx = padx
        self._pady = pady
        self._radius = radius
        self._enabled = True

        # 用 tkinter.font.Font 正确测量文字尺寸（兼容含空格的字体名）
        from tkinter import font as tkfont
        fnt = tkfont.Font(font=font)
        self._h = fnt.metrics('linespace') + pady * 2
        self._bw = width if width else fnt.measure(text) + padx * 2
        self._font = font

        super().__init__(parent, width=self._bw, height=self._h,
                         highlightthickness=0, bd=0, **kw)
        self._draw(self._bg)

        self.bind('<Enter>', self._on_enter, add='+')
        self.bind('<Leave>', self._on_leave, add='+')
        self.bind('<ButtonPress-1>', self._on_press, add='+')
        self.bind('<ButtonRelease-1>', self._on_release, add='+')

    def _draw(self, fill):
        self.delete('all')
        self._round_rect(0, 0, self._bw, self._h, self._radius, fill=fill)
        self.create_text(self._bw / 2, self._h / 2, text=self._text,
                         fill=self._fg, font=self._font)

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
               x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(pts, smooth=True, **kw)

    def _on_enter(self, _e):
        if self._enabled:
            self._draw(lighten(self._bg, 0.08))
            self.configure(cursor='hand2')

    def _on_leave(self, _e):
        if self._enabled:
            self._draw(self._bg)

    def _on_press(self, _e):
        if self._enabled:
            self._draw(self._active)

    def _on_release(self, _e):
        if self._enabled:
            self._draw(lighten(self._bg, 0.08))
            if self._command:
                self._command()

    def set_enabled(self, enabled):
        self._enabled = enabled
        if enabled:
            self._draw(self._bg)
            self.configure(cursor='hand2')
        else:
            self._draw(THEME_COLORS['fill'])
            self.itemconfig('all', fill=THEME_COLORS['text_secondary'])
            # 文字单独再设回次要色
            self._draw_disabled()

    def _draw_disabled(self):
        self.delete('all')
        self._round_rect(0, 0, self._bw, self._h, self._radius, fill=THEME_COLORS['fill'])
        self.create_text(self._bw / 2, self._h / 2, text=self._text,
                         fill=THEME_COLORS['text_secondary'], font=self._font)


# ========== ttk 样式配置 ==========

def apply_theme(root):
    """对根窗口应用 Professional Scientific 主题，配置所有 ttk 组件样式。"""
    C = THEME_COLORS
    F = THEME_FONTS
    root.configure(bg=C['background'])

    style = ttk.Style(root)
    try:
        style.theme_use('clam')  # clam 最便于自定义颜色
    except tk.TclError:
        pass

    # 全局
    style.configure('.', background=C['background'], foreground=C['text'],
                    font=F['body'], bordercolor=C['border'],
                    lightcolor=C['border'], darkcolor=C['border'])

    # TLabel
    style.configure('TLabel', background=C['background'], foreground=C['text'], font=F['body'])
    style.configure('Title.TLabel', background=C['background'], foreground=C['primary'], font=F['title'])
    style.configure('Section.TLabel', background=C['background'], foreground=C['text'], font=F['section'])
    style.configure('Secondary.TLabel', background=C['background'], foreground=C['text_secondary'], font=F['body'])
    style.configure('Accent.TLabel', background=C['background'], foreground=C['primary_light'], font=F['accent_value'])

    # LabelFrame —— 浅灰底 + 1px 实线边框
    style.configure('TLabelframe', background=C['card_translucent'],
                    bordercolor=C['border'], borderwidth=1, relief='solid')
    style.configure('TLabelframe.Label', background=C['card_translucent'],
                    foreground=C['text'], font=F['section'])

    # TFrame / 卡片
    style.configure('TFrame', background=C['background'])
    style.configure('Card.TFrame', background=C['card_translucent'])

    # Notebook 选项卡
    style.configure('TNotebook', background=C['background'], borderwidth=0, tabmargins=(4, 0, 4, 0))
    style.configure('TNotebook.Tab', background=C['fill'], foreground=C['text_secondary'],
                    padding=(20, 10), font=F['tab'])
    style.map('TNotebook.Tab',
              background=[('selected', C['primary']), ('active', C['card_translucent'])],
              foreground=[('selected', '#FFFFFF'), ('active', C['text'])])

    # Entry / Spinbox / Combobox
    style.configure('TEntry', fieldbackground=C['fill_light'], bordercolor=C['border'],
                    borderwidth=1, padding=(6, 4))
    style.map('TEntry',
              fieldbackground=[('focus', C['card'])],
              bordercolor=[('focus', C['primary_light'])],
              lightcolor=[('focus', C['primary_light'])],
              darkcolor=[('focus', C['primary_light'])])

    style.configure('TCombobox', fieldbackground=C['fill_light'], background=C['background'],
                    bordercolor=C['border'], borderwidth=1, padding=(6, 4),
                    arrowcolor=C['text_secondary'])
    style.map('TCombobox',
              fieldbackground=[('focus', C['card'])],
              bordercolor=[('focus', C['primary_light'])])
    # 下拉列表
    root.option_add('*TCombobox*Listbox.background', C['card'])
    root.option_add('*TCombobox*Listbox.foreground', C['text'])
    root.option_add('*TCombobox*Listbox.selectBackground', C['primary_light'])
    root.option_add('*TCombobox*Listbox.selectForeground', '#FFFFFF')
    root.option_add('*TCombobox*Listbox.font', F['body'])

    style.configure('TSpinbox', fieldbackground=C['fill_light'], bordercolor=C['border'],
                    borderwidth=1, padding=(6, 4), arrowcolor=C['text_secondary'])
    style.map('TSpinbox',
              fieldbackground=[('focus', C['card'])],
              bordercolor=[('focus', C['primary_light'])])

    # Treeview 表格
    style.configure('Treeview', background=C['card'], fieldbackground=C['card'],
                    foreground=C['text'], rowheight=30, borderwidth=0, font=F['body'])
    style.configure('Treeview.Heading', background=C['card_translucent'],
                    foreground=C['text_secondary'], font=F['label_bold'], relief='flat')
    style.map('Treeview',
              background=[('selected', C['primary_light'])],
              foreground=[('selected', '#FFFFFF')])
    style.map('Treeview.Heading', background=[('active', C['fill'])])

    # Checkbutton / Radiobutton
    style.configure('TCheckbutton', background=C['card_translucent'],
                    foreground=C['text'], font=F['body'])
    style.map('TCheckbutton',
              background=[('active', C['card_translucent'])])
    style.configure('TRadiobutton', background=C['card_translucent'],
                    foreground=C['text'], font=F['body'])

    # Scrollbar
    style.configure('TScrollbar', background=C['fill'], troughcolor=C['background'],
                    bordercolor=C['background'], arrowcolor=C['text_secondary'],
                    arrowsize=12)
    style.map('TScrollbar', background=[('active', C['card_translucent'])])

    # Progressbar
    style.configure('Horizontal.TProgressbar', background=C['accent'],
                    troughcolor=C['fill'], borderwidth=0, thickness=8)
    style.map('Horizontal.TProgressbar', background=[('active', C['accent_dark'])])

    # Separator
    style.configure('TSeparator', background=C['border'])
