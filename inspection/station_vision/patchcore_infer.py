"""
patchcore_infer.py — 학습된 PatchCore 모델(anomalib)로 사진 1장의 이상 점수를 내는 모듈

학습은 inspection/visionPatchCore/patchcore_export/patchcore.py 가 하고 (그 폴더는 건드리지 않음),
여기서는 그 결과 모델 파일(models/v3/model.ckpt)을 읽어서 검사에만 쓴다.

    from patchcore_infer import PatchCoreInspector
    pc = PatchCoreInspector()                       # 기본: v3 모델, CPU
    r = pc.inspect(frame_bgr)                       # OpenCV 프레임 (BGR)
    r["score"], r["threshold"], r["anomalous"]      # 이상 점수(0~1), 판정 기준, 불합격 여부
    r["heatmap"]                                    # 원본 위에 이상 위치를 겹친 그림 (BGR)

점수와 기준은 모델에 저장된 후처리(정규화)를 그대로 쓴다: 점수 >= 기준이면 불합격.
DB 의 PatchCore 판정(db_client.send_patchcore)과 같은 규칙이다.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
# 학습 결과 모델 (visionPatchCore 폴더 안, 읽기만 함). config.py 의 PATCHCORE_MODEL 로 바꿀 수 있다
DEFAULT_MODEL = ROOT.parent / "visionPatchCore" / "patchcore_export" / "models" / "v3" / "model.ckpt"


class PatchCoreInspector:
    def __init__(self, model_path: str | Path | None = None, device: str = "cpu"):
        import torch
        from anomalib.models import Patchcore

        self.model_path = Path(model_path or DEFAULT_MODEL)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"PatchCore 모델 파일이 없습니다: {self.model_path}")
        self.torch = torch
        self.device = device
        self.version = f"patchcore-{self.model_path.parent.name}"  # DB 의 patchcore_model_version (예: patchcore-v3)
        # anomalib 체크포인트에는 전처리·후처리 객체가 같이 들어 있어서 weights_only=False 로 읽어야 한다.
        # (파일 안의 코드가 실행될 수 있으므로 우리 팀이 학습한 모델 파일만 넣을 것)
        self.model = Patchcore.load_from_checkpoint(str(self.model_path), map_location=device, weights_only=False)
        self.model.eval().to(device)
        # Keep the checkpoint's normalization, but reject a different spatial transform.
        self.image_size = self._image_size()
        if self.image_size != (320, 600):
            raise ValueError(f"PatchCore 모델 입력 크기가 학습 조건과 다릅니다: {self.image_size}, 필요=(320, 600)")
        self.last_input_shape = None
        self.last_feature_input_shape = None
        self.model.model.register_forward_pre_hook(self._check_feature_input)
        # 정규화된 점수의 판정 기준. anomalib 후처리는 학습 때 구한 기준을 0.5 로 맞춘다
        self.threshold = float(getattr(getattr(self.model, "post_processor", None), "normalized_image_threshold", 0.5))

    def _image_size(self):
        try:
            for t in self.model.pre_processor.transform.transforms:
                if hasattr(t, "size"):
                    size = t.size
                    return tuple(size) if isinstance(size, (list, tuple)) else (size, size)
        except AttributeError:
            return None
        return None

    def inspect(self, frame_bgr: np.ndarray) -> dict:
        """사진 1장 → {"score", "threshold", "anomalous", "heatmap"}"""
        if frame_bgr.shape != (320, 600, 3):
            raise ValueError(f"PatchCore ROI shape={frame_bgr.shape}; 필요=(320, 600, 3). 자동 resize하지 않습니다.")
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        tensor = self.torch.from_numpy(rgb).permute(2, 0, 1).float().div(255).unsqueeze(0).to(self.device)
        self.last_input_shape = tuple(tensor.shape)
        with self.torch.no_grad():
            out = self.model(tensor)  # 모델이 전처리(크기 조정·정규화)와 후처리(점수 정규화)를 같이 한다
        score = float(out.pred_score.reshape(-1)[0].cpu())
        amap = out.anomaly_map.reshape(out.anomaly_map.shape[-2:]).cpu().numpy() if out.anomaly_map is not None else None
        return {"score": round(score, 6), "threshold": self.threshold, "anomalous": score >= self.threshold,
                "heatmap": overlay(frame_bgr, amap)}

    def _check_feature_input(self, _module, args):
        """Verify the actual tensor after the checkpoint preprocessor as well."""
        self.last_feature_input_shape = tuple(args[0].shape)
        if self.last_feature_input_shape != (1, 3, 320, 600):
            raise ValueError(f"PatchCore 전처리 후 shape 오류: {self.last_feature_input_shape}")


def overlay(frame_bgr: np.ndarray, amap: np.ndarray | None) -> np.ndarray:
    """이상 지도(0~1)를 컬러로 바꿔 원본 위에 반투명하게 겹친다"""
    if amap is None:
        return frame_bgr.copy()
    h, w = frame_bgr.shape[:2]
    amap = cv2.resize(np.clip(amap, 0, 1).astype(np.float32), (w, h))
    color = cv2.applyColorMap((amap * 255).astype(np.uint8), cv2.COLORMAP_JET)
    return cv2.addWeighted(color, 0.45, frame_bgr, 0.55, 0)
