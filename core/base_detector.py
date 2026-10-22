"""检测器基类 - 定义统一接口"""

from abc import ABC, abstractmethod


class BaseHandDetector(ABC):
    """手部检测器抽象基类"""

    # 手部连接线定义（21点标准）
    HAND_CONNECTIONS = [
        (0, 1), (1, 2), (2, 3), (3, 4),  # 拇指
        (0, 5), (5, 6), (6, 7), (7, 8),  # 食指
        (0, 9), (9, 10), (10, 11), (11, 12),  # 中指
        (0, 13), (13, 14), (14, 15), (15, 16),  # 无名指
        (0, 17), (17, 18), (18, 19), (19, 20),  # 小指
        (5, 9), (9, 13), (13, 17)  # 掌心连接
    ]

    @abstractmethod
    def detect(self, frame_rgb):
        """检测手部

        Args:
            frame_rgb: RGB格式的图像帧

        Returns:
            检测结果（格式由具体实现定义）
        """
        pass

    @abstractmethod
    def get_landmarks(self, results, frame_shape):
        """获取21个关键点坐标

        Args:
            results: detect()返回的结果
            frame_shape: 帧尺寸 (height, width, ...)

        Returns:
            list: 21个关键点 [(x, y, z), ...] 或 None
        """
        pass

    @abstractmethod
    def draw(self, frame, results):
        """在帧上绘制检测结果

        Args:
            frame: BGR格式的图像帧
            results: detect()返回的结果

        Returns:
            绘制后的帧
        """
        pass

    @abstractmethod
    def release(self):
        """释放资源"""
        pass

    @property
    def name(self):
        """检测器名称"""
        return self.__class__.__name__
