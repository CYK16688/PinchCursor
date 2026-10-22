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
        cls.ICONS["point"] = '''<path d="M224,104v50.93c0,46.2-36.85,84.55-83,85.06A83.71,83.71,0,0,1,80.6,215.4C58.79,192.33,34.15,136,34.15,136a16,16,0,0,1,6.53-22.23c7.66-4,17.1-.84,21.4,6.62l21,36.44a6.09,6.09,0,0,0,6,3.09l.12,0A8.19,8.19,0,0,0,96,151.74V32a16,16,0,0,1,16.77-16c8.61.4,15.23,7.82,15.23,16.43V104a8,8,0,0,0,8.53,8,8.17,8.17,0,0,0,7.47-8.25V88a16,16,0,0,1,16.77-16c8.61.4,15.23,7.82,15.23,16.43V112a8,8,0,0,0,8.53,8,8.17,8.17,0,0,0,7.47-8.25v-7.28c0-8.61,6.62-16,15.23-16.43A16,16,0,0,1,224,104Z"/>'''

        # 捏合/点击 - hand-tap-fill
        cls.ICONS["pinch"] = '''<path d="M64,64a48,48,0,0,1,96,0,8,8,0,0,1-16,0,32,32,0,0,0-64,0,8,8,0,0,1-16,0Zm143.23,56c-8.61.4-15.23,7.82-15.23,16.43v7.28a8.17,8.17,0,0,1-7.47,8.25,8,8,0,0,1-8.53-8V120.45c0-8.61-6.62-16-15.23-16.43A16,16,0,0,0,144,120v15.73a8.17,8.17,0,0,1-7.47,8.25,8,8,0,0,1-8.53-8V64.45c0-8.61-6.62-16-15.23-16.43A16,16,0,0,0,96,64V183.74a8.19,8.19,0,0,1-6.72,8.16l-.12,0a6.09,6.09,0,0,1-6-3.09l-21-36.44c-4.3-7.46-13.74-10.57-21.4-6.62A16,16,0,0,0,34.15,168L65.1,228.05A8,8,0,0,0,72,232H208a8,8,0,0,0,7.16-4.42c.36-.72,8.84-15.06,8.84-40.65V136A16,16,0,0,0,207.23,120Z"/>'''

        # 捏合长按/拖动 - hand-grabbing-fill
        cls.ICONS["pinch_hold"] = '''<path d="M216,104v48a88,88,0,0,1-176,0V136a16,16,0,0,1,32,0v8a8,8,0,0,0,16,0V88a16,16,0,0,1,32,0v16a8,8,0,0,0,16,0V88a16,16,0,0,1,32,0v16a8,8,0,0,0,16,0,16,16,0,0,1,32,0Z"/>'''

        # 张开手掌 - hand-fill
        cls.ICONS["open_hand"] = '''<path d="M216,64v90.93c0,46.2-36.85,84.55-83,85.06A83.71,83.71,0,0,1,72.6,215.4C50.79,192.33,26.15,136,26.15,136a16,16,0,0,1,6.53-22.23c7.66-4,17.1-.84,21.4,6.62l21,36.44a6.09,6.09,0,0,0,6,3.09l.12,0A8.19,8.19,0,0,0,88,151.74V48a16,16,0,0,1,16.77-16c8.61.4,15.23,7.82,15.23,16.43V112a8,8,0,0,0,8.53,8,8.17,8.17,0,0,0,7.47-8.25V32a16,16,0,0,1,16.77-16c8.61.4,15.23,7.82,15.23,16.43V120a8,8,0,0,0,8.53,8,8.17,8.17,0,0,0,7.47-8.25V64.45c0-8.61,6.62-16,15.23-16.43A16,16,0,0,1,216,64Z"/>'''

        # 拇指向上 - thumbs-up-fill
        cls.ICONS["thumb_up"] = '''<path d="M234,80.12A24,24,0,0,0,216,72H160V56a40,40,0,0,0-40-40,8,8,0,0,0-7.16,4.42L75.06,96H32a16,16,0,0,0-16,16v88a16,16,0,0,0,16,16H204a24,24,0,0,0,23.82-21l12-96A24,24,0,0,0,234,80.12ZM32,112H72v88H32Z"/>'''

        # 拇指向下 - thumbs-down-fill
        cls.ICONS["thumb_down"] = '''<path d="M239.82,157l-12-96A24,24,0,0,0,204,40H32A16,16,0,0,0,16,56v88a16,16,0,0,0,16,16H75.06l37.78,75.58A8,8,0,0,0,120,240a40,40,0,0,0,40-40V184h56a24,24,0,0,0,23.82-27ZM72,144H32V56H72Z"/>'''

        # 握拳 - hand-fist-fill
        cls.ICONS["fist"] = '''<path d="M232,120v8A104,104,0,0,1,127.63,232c-54-.19-98-42.06-103.12-94.78a4,4,0,0,1,5.56-4A35.94,35.94,0,0,0,72,122.59a35.92,35.92,0,0,0,53.94,2.33a40.36,40.36,0,0,0,12.87,13A47.94,47.94,0,0,0,120,176a8,8,0,0,0,8.67,8,8.21,8.21,0,0,0,7.33-8.26A32,32,0,0,1,168,144a8,8,0,0,0,8-8.53,8.18,8.18,0,0,0-8.25-7.47H160a24,24,0,0,1-24-24V88h64A32,32,0,0,1,232,120ZM44.73,120C55.57,119.6,64,110.37,64,99.52v-23C64,65.63,55.57,56.4,44.73,56A20,20,0,0,0,24,76v24A20,20,0,0,0,44.73,120Zm56,0c10.84-.39,19.27-9.62,19.27-20.47v-47c0-10.85-8.43-20.08-19.27-20.47A20,20,0,0,0,80,52v48A20,20,0,0,0,100.73,120ZM176,52a20,20,0,0,0-20.73-20C144.43,32.4,136,41.63,136,52.48V72h36a4,4,0,0,0,4-4Z"/>'''

        # 剪刀手/和平 - 自定义V字手势 (Phosphor没有peace手势)
        cls.ICONS["peace"] = '''<path d="M116,32a16,16,0,0,0-16,16v54.7L66.4,70.4a16,16,0,0,0-22.6,22.6L88,137.2V216a16,16,0,0,0,32,0V137.2l44.2-44.2a16,16,0,0,0-22.6-22.6L108,103.7V48A16,16,0,0,0,92,32Z M140,32a16,16,0,0,1,16,16v54.7l33.6-32.3a16,16,0,0,1,22.6,22.6L168,137.2V216a16,16,0,0,1-32,0V48A16,16,0,0,1,140,32Z"/>
        <rect x="80" y="140" width="96" height="80" rx="24"/>
        <rect x="92" y="24" width="24" height="120" rx="12"/>
        <rect x="140" y="24" width="24" height="120" rx="12"/>'''

        # OK手势 - 自定义圆圈手势
        cls.ICONS["ok"] = '''<circle cx="80" cy="100" r="36" fill="none" stroke="{color}" stroke-width="20"/>
        <rect x="140" y="40" width="20" height="80" rx="10"/>
        <rect x="172" y="48" width="20" height="72" rx="10"/>
        <rect x="204" y="56" width="20" height="64" rx="10"/>
        <path d="M60,150 Q60,220 128,220 Q196,220 196,150 L196,140 L60,140 Z"/>'''

        # 摇滚手势 - 食指+小指伸出
        cls.ICONS["rock"] = '''<rect x="56" y="24" width="24" height="100" rx="12"/>
        <rect x="176" y="24" width="24" height="100" rx="12"/>
        <path d="M48,130 Q48,220 128,220 Q208,220 208,130 L208,120 L48,120 Z"/>'''

        # 三指 - 食指中指无名指伸出
        cls.ICONS["three"] = '''<rect x="72" y="20" width="24" height="108" rx="12"/>
        <rect x="116" y="16" width="24" height="112" rx="12"/>
        <rect x="160" y="20" width="24" height="108" rx="12"/>
        <path d="M56,132 Q56,224 128,224 Q200,224 200,132 L200,124 L56,124 Z"/>'''

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
