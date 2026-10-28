"""SVG手势图标 - 使用Phosphor Icons开源图标库 (MIT License)
https://github.com/phosphor-icons/core
"""

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QPainter


class GestureIconsSVG:
    """SVG手势图标管理器 - Phosphor Icons"""

    ICON_COLOR = "#e8eaed"

    # Phosphor Icons 使用 256x256 viewBox
    SVG_TEMPLATE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="{color}">{path}</svg>'

    ICONS = {}

    @classmethod
    def _init_icons(cls):
        """初始化 Phosphor Icons 手势图标"""
        if cls.ICONS:
            return

        # 指向 - hand-pointing-fill
        cls.ICONS["point"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <rect x="88" y="16" width="32" height="120" rx="16"/>
        <path d="M120 96h32a16 16 0 0 1 16 16v8"/>
        <path d="M168 120a16 16 0 0 1 16 16v14"/>
        <path d="M34 150l22 40a40 40 0 0 0 35 21h69a40 40 0 0 0 40-40v-35"/></g>'''

        # 捏合/点击 - hand-tap-fill
        cls.ICONS["pinch"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="112" cy="60" r="30"/>
        <rect x="88" y="96" width="32" height="104" rx="16"/>
        <path d="M152 104h28a16 16 0 0 1 16 16v98a24 24 0 0 1-24 24h-79a40 40 0 0 1-35-20l-22-38"/></g>'''

        # 捏合长按/拖动 - hand-grabbing-fill
        cls.ICONS["pinch_hold"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="128" cy="72" r="34"/>
        <path d="M128 106v38"/>
        <rect x="52" y="144" width="34" height="82" rx="17"/>
        <rect x="170" y="144" width="34" height="82" rx="17"/>
        <path d="M69 144h118"/>
        <path d="M69 226h118"/></g>'''

        # 张开手掌 - hand-fill
        cls.ICONS["open_hand"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <rect fill="none" stroke="{color}" stroke-width="16" x="56" y="72" width="30" height="96" rx="15"/>
        <rect x="96" y="40" width="30" height="128" rx="15"/>
        <rect x="136" y="56" width="30" height="112" rx="15"/>
        <rect fill="none" stroke="{color}" stroke-width="16" x="176" y="80" width="30" height="88" rx="15"/>
        <path d="M40 152v24a48 48 0 0 0 48 48h80a48 48 0 0 0 48-48v-32"/></g>'''

        # 拇指向上 - thumbs-up-fill
        cls.ICONS["thumb_up"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <rect x="24" y="104" width="48" height="112" rx="12"/>
        <path d="M72 200V112l48-88a24 24 0 0 1 24 24v40h56a20 20 0 0 1 20 24l-14 84a24 24 0 0 1-24 20H72"/></g>'''

        # 拇指向下 - thumbs-down-fill
        cls.ICONS["thumb_down"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <rect x="24" y="40" width="48" height="112" rx="12"/>
        <path d="M72 56v88l48 88a24 24 0 0 0 24-24v-40h56a20 20 0 0 0 20-24l-14-84a24 24 0 0 0-24-20H72"/></g>'''

        # 握拳 - hand-fist-fill
        cls.ICONS["fist"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <path d="M48 128V88a20 20 0 0 1 40 0v8a20 20 0 0 1 40 0v-8a20 20 0 0 1 40 0v16a20 20 0 0 1 40 0v48a64 64 0 0 1-64 64H112a64 64 0 0 1-64-64z"/></g>'''

        # 剪刀手/和平 - 自定义V字手势 (Phosphor没有peace手势)
        cls.ICONS["peace"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <path d="M92 32v72L66 76a16 16 0 0 0-23 23l50 50v75"/>
        <path d="M164 32v72l26-28a16 16 0 0 1 23 23l-50 50v75"/>
        <path d="M92 224h72"/></g>'''

        # OK手势 - 自定义圆圈手势
        cls.ICONS["ok"] = '''<circle cx="80" cy="100" r="36" fill="none" stroke="{color}" stroke-width="20"/>
        <rect fill="none" stroke="{color}" stroke-width="16" x="140" y="40" width="20" height="80" rx="10"/>
        <rect fill="none" stroke="{color}" stroke-width="16" x="172" y="48" width="20" height="72" rx="10"/>
        <rect fill="none" stroke="{color}" stroke-width="16" x="204" y="56" width="20" height="64" rx="10"/>
        <path d="M60,150 Q60,220 128,220 Q196,220 196,150" fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round"/>'''

        # 我爱你手势 - 拇指+食指+小指伸出
        cls.ICONS["ilove_you"] = '''<g fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round">
        <rect x="52" y="88" width="30" height="96" rx="15"/>
        <rect x="92" y="40" width="30" height="144" rx="15"/>
        <rect x="132" y="96" width="30" height="88" rx="15"/>
        <rect x="172" y="40" width="30" height="144" rx="15"/>
        <path d="M40 160v16a56 56 0 0 0 56 56h64a56 56 0 0 0 56-56v-36"/></g>'''

        # 摇滚手势 - 食指+小指伸出
        cls.ICONS["rock"] = '''<rect fill="none" stroke="{color}" stroke-width="16" x="56" y="24" width="24" height="100" rx="12"/>
        <rect fill="none" stroke="{color}" stroke-width="16" x="176" y="24" width="24" height="100" rx="12"/>
        <path d="M48,130 Q48,220 128,220 Q208,220 208,130" fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round"/>'''

        # 三指 - 食指中指无名指伸出
        cls.ICONS["three"] = '''<rect fill="none" stroke="{color}" stroke-width="16" x="72" y="20" width="24" height="108" rx="12"/>
        <rect fill="none" stroke="{color}" stroke-width="16" x="116" y="16" width="24" height="112" rx="12"/>
        <rect fill="none" stroke="{color}" stroke-width="16" x="160" y="20" width="24" height="108" rx="12"/>
        <path d="M56,132 Q56,224 128,224 Q200,224 200,132" fill="none" stroke="{color}" stroke-width="16" stroke-linecap="round"/>'''

    @classmethod
    def get_renderer(cls, gesture_id, color=None):
        """获取SVG渲染器"""
        cls._init_icons()

        if gesture_id not in cls.ICONS:
            return None

        color = color or cls.ICON_COLOR
        # 替换路径中的颜色占位符
        path_content = cls.ICONS[gesture_id].replace("{color}", color)
        svg_content = cls.SVG_TEMPLATE.format(color=color, path=path_content)

        renderer = QSvgRenderer(QByteArray(svg_content.encode()))
        return renderer if renderer.isValid() else None

    @classmethod
    def pixmap(cls, gesture_id, size=22, color=None):
        """Rasterise one gesture glyph for a row or a legend."""
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap

        renderer = cls.get_renderer(gesture_id, color)
        if renderer is None:
            return None
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        return pixmap

    @classmethod
    def draw(cls, painter, rect, gesture_id, color=None):
        """绘制SVG图标到指定区域"""
        renderer = cls.get_renderer(gesture_id, color)
        if renderer:
            renderer.render(painter, QRectF(rect))
            return True
        return False

    @classmethod
    def get_draw_func(cls, gesture_id):
        """获取绘制函数（兼容旧接口）"""
        def draw_func(painter, rect):
            cls.draw(painter, rect, gesture_id)
        return draw_func
