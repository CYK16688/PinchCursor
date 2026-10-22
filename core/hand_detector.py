"""手部检测模块 - 基于 MediaPipe Tasks API"""

import time
from math import isfinite

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from core.base_detector import BaseHandDetector
from core.resource_paths import model_resource_path


class HandDetector(BaseHandDetector):
    """使用 MediaPipe Tasks API 检测手部关键点"""

    def __init__(self, detection_conf=0.7, tracking_conf=0.5, delegate="cpu"):
        self._model_path = str(model_resource_path())
        self._detection_conf = detection_conf
        self._tracking_conf = tracking_conf
        self._requested_delegate = "gpu" if delegate == "gpu" else "cpu"
        self.delegate = self._requested_delegate
        self.color_format = self._color_format_for(self.delegate)
        self.detector = self._build(self.delegate)
        self.last_result = None
        self._last_timestamp_ms = -1

    @staticmethod
    def _color_format_for(delegate):
        """Metal only accepts four-channel textures; give it RGBA."""
        return "rgba" if delegate == "gpu" else "rgb"

    def _build(self, delegate):
        delegate_enum = (
            python.BaseOptions.Delegate.GPU
            if delegate == "gpu"
            else python.BaseOptions.Delegate.CPU
        )
        base_options = python.BaseOptions(
            model_asset_path=self._model_path, delegate=delegate_enum
        )
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=self._detection_conf,
            min_tracking_confidence=self._tracking_conf,
        )
        return vision.HandLandmarker.create_from_options(options)

    def _fall_back_to_cpu(self):
        """Drop to CPU once, if a GPU graph cannot run on this machine."""
        if self.delegate != "gpu":
            return False
        self.delegate = "cpu"
        self.color_format = self._color_format_for("cpu")
        self.detector = self._build("cpu")
        return True

    def detect(self, frame_rgb):
        """Compatibility wrapper for callers not yet using VIDEO timestamps."""
        return self.detect_for_video(frame_rgb, int(time.monotonic() * 1000))

    def detect_for_video(self, frame_rgb, timestamp_ms):
        """检测视频帧的手部关键点，使用严格递增的时间戳。

        ``frame_rgb`` must match ``color_format``: RGBA for the Metal delegate,
        RGB otherwise. A GPU graph that refuses to run is retried once on CPU
        rather than leaving control permanently broken.
        """
        image_format = (
            mp.ImageFormat.SRGBA if self.color_format == "rgba" else mp.ImageFormat.SRGB
        )
        mp_image = mp.Image(image_format=image_format, data=frame_rgb)
        timestamp_ms = max(int(timestamp_ms), self._last_timestamp_ms + 1)
        self._last_timestamp_ms = timestamp_ms
        try:
            self.last_result = self.detector.detect_for_video(mp_image, timestamp_ms)
        except (RuntimeError, ValueError, TypeError):
            if not self._fall_back_to_cpu():
                raise
            # The caller handed us RGBA for the GPU; the CPU graph wants RGB.
            retry_frame = frame_rgb
            shape = getattr(frame_rgb, "shape", None)
            if shape is not None and len(shape) == 3 and shape[2] == 4:
                retry_frame = frame_rgb[:, :, :3]
            return self.detect_for_video(retry_frame, timestamp_ms + 1)
        return self.last_result

    def get_landmarks(self, results, frame_shape):
        """获取21个关键点的像素坐标和3D坐标"""
        if not results.hand_landmarks:
            return None

        hand_lms = results.hand_landmarks[0]
        if len(hand_lms) != 21:
            return None
        h, w = frame_shape[:2]

        landmarks = []
        try:
            for lm in hand_lms:
                x, y, z = float(lm.x), float(lm.y), float(lm.z)
                if not all(isfinite(value) for value in (x, y, z)):
                    return None
                # 返回(x像素, y像素, z深度)
                landmarks.append((int(x * w), int(y * h), z))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None
        return landmarks

    def draw(self, frame, results):
        """绘制手部关键点"""
        if not results.hand_landmarks:
            return frame

        h, w = frame.shape[:2]
        for hand_lms in results.hand_landmarks:
            # 绘制关键点
            for lm in hand_lms:
                x, y = int(lm.x * w), int(lm.y * h)
                cv2.circle(frame, (x, y), 5, (0, 255, 0), -1)

            # 绘制连接线
            for conn in self.HAND_CONNECTIONS:
                p1 = hand_lms[conn[0]]
                p2 = hand_lms[conn[1]]
                x1, y1 = int(p1.x * w), int(p1.y * h)
                x2, y2 = int(p2.x * w), int(p2.y * h)
                cv2.line(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        return frame

    def release(self):
        """释放资源"""
        self.detector.close()
