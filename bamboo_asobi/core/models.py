"""データクラス群"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.constants import BAMBOO_WALL_RATIO


# ══════════════════════════════════════════════════════════════════
# データクラス群
# ══════════════════════════════════════════════════════════════════
@dataclass
class Dimensions:
    """すべての寸法をメートル単位で管理するデータクラス"""
    height_m:   float
    width_m:    float
    length_m:   float
    diameter_m: float

    @property
    def diameter_cm(self) -> float:
        return self.diameter_m * 100

    @property
    def height_cm(self) -> float:
        return self.height_m * 100

    @property
    def width_cm(self) -> float:
        return self.width_m * 100

    @property
    def length_cm(self) -> float:
        return self.length_m * 100

    @property
    def section_I(self) -> float:
        """中空円管の断面二次モーメント [m^4]"""
        di = self.diameter_m * (1.0 - 2 * BAMBOO_WALL_RATIO)
        return math.pi * (self.diameter_m**4 - di**4) / 64

    @property
    def section_Z(self) -> float:
        """断面係数 [m^3]"""
        return self.section_I / (self.diameter_m / 2)


@dataclass
class Material:
    name:      str
    length_cm: int
    count:     int
    is_wood:   bool = False
    is_rope:   bool = False


@dataclass
class CheckMessage:
    level:  str          # "危険" | "警告" | "注意"
    msg:    str
    advice: str = ""


@dataclass
class StructuralResult:
    ok:     bool
    value:  float
    error:  str = ""
