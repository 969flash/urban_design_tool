# -*- coding: utf-8 -*-
"""RoadDetailBuilder main entry for Grasshopper (Rhino 8 / Python 3).

본 스크립트는 Rhino 문서 내 레이어에서 도로 중심선을 읽어 상세 라인 요소
(중앙선, 차선, 가장자리 선)을 생성합니다. utils.py의 컨벤션(타입 힌트,
Google 스타일 Docstring, snake_case, geo 별칭)을 따릅니다.

주의:
- Grasshopper Python 3 컴포넌트에서 실행을 가정합니다.
- 프로젝트의 constants.py가 없을 경우 안전한 기본값으로 대체합니다.
"""

from typing import List, Tuple, Optional, Union, Any
import math

import Rhino
import Rhino.Geometry as geo
import scriptcontext as sc
import ghpythonlib.components as ghcomp
import System

# constants.py의 모든 상수 임포트 (단일 소스 관리)
from constants import *  # type: ignore  # noqa: F401,F403

# 프로젝트 유틸 전부 임포트
from utils import *  # noqa: F401,F403

# 디버그 플래그 (GH 실행부에서 설정)
_DEBUG: bool = True


def debug_print(*args: Any) -> None:
    """디버그가 활성화된 경우에만 메시지를 출력합니다."""
    if _DEBUG:
        try:
            print(*args)
        except Exception:
            pass


# ==============================================================================
# 내부 유틸리티 (레이어/오프셋/로프트 헬퍼)
# ==============================================================================


def _get_model_tol(doc: Optional[Rhino.RhinoDoc]) -> float:
    """문서 공차를 반환합니다.

    Args:
        doc (Optional[Rhino.RhinoDoc]): Rhino 문서.

    Returns:
        float: 사용 가능한 공차 값.
    """
    try:
        if doc and hasattr(doc, "ModelAbsoluteTolerance"):
            return float(doc.ModelAbsoluteTolerance)
    except Exception:
        pass
    try:
        # constants.TOL 이 존재하는 경우
        from constants import TOL as _TOL  # type: ignore

        return float(_TOL)
    except Exception:
        return 1e-3


def _ensure_layer(doc: Rhino.RhinoDoc, full_layer_name: str) -> int:
    """전체 경로 기반 레이어를 보장 생성하고 인덱스를 반환합니다.

    'A::B::C' 형식의 레이어 경로를 지원합니다.

    Args:
        doc (Rhino.RhinoDoc): 문서.
        full_layer_name (str): 전체 경로 레이어 이름.

    Returns:
        int: 생성/존재 레이어의 인덱스. 실패 시 -1.
    """
    try:
        if not full_layer_name:
            return -1
        # 이미 존재하면 즉시 반환
        idx = doc.Layers.FindByFullPath(full_layer_name, -1)
        if idx != -1:
            debug_print("[layer] exists:", full_layer_name, "index=", idx)
            return idx

        parts = [p for p in full_layer_name.split("::") if p]
        parent_id = None
        current_path = ""
        for part in parts:
            current_path = part if not current_path else current_path + "::" + part
            existing = doc.Layers.FindByFullPath(current_path, -1)
            if existing != -1:
                parent_id = doc.Layers[existing].Id
                debug_print("[layer] found part:", current_path)
                continue

            layer = Rhino.DocObjects.Layer()
            layer.Name = part
            if parent_id is not None:
                layer.ParentLayerId = parent_id
            new_index = doc.Layers.Add(layer)
            if new_index < 0:
                return -1
            parent_id = doc.Layers[new_index].Id
            debug_print("[layer] created part:", current_path, "index=", new_index)
        final_idx = doc.Layers.FindByFullPath(full_layer_name, -1)
        debug_print("[layer] ready:", full_layer_name, "index=", final_idx)
        return final_idx
    except Exception:
        return -1


def _add_geometry(doc: Rhino.RhinoDoc, geom: Any, layer_index: int) -> bool:
    """지오메트리를 지정 레이어에 추가(bake)합니다.

    Args:
        doc (Rhino.RhinoDoc): Rhino 문서.
        geom (Any): 추가할 지오메트리.
        layer_index (int): 대상 레이어 인덱스.

    Returns:
        bool: 성공 여부.
    """
    try:
        if geom is None:
            return False
        attr = Rhino.DocObjects.ObjectAttributes()
        attr.LayerIndex = layer_index

        # 타입별로 안전하게 추가
        if isinstance(geom, geo.Brep):
            return doc.Objects.AddBrep(geom, attr) != System.Guid.Empty  # type: ignore
        if isinstance(geom, geo.Surface):
            brep = geom.ToBrep()
            return doc.Objects.AddBrep(brep, attr) != System.Guid.Empty  # type: ignore
        if isinstance(geom, geo.Curve):
            return doc.Objects.AddCurve(geom, attr) != System.Guid.Empty  # type: ignore
        if isinstance(geom, geo.Mesh):
            return doc.Objects.AddMesh(geom, attr) != System.Guid.Empty  # type: ignore
        # 그 외 시도: ToBrep 보유 시
        if hasattr(geom, "ToBrep"):
            try:
                brep = geom.ToBrep()
                return doc.Objects.AddBrep(brep, attr) != System.Guid.Empty  # type: ignore
            except Exception:
                pass
        return False
    except Exception:
        return False


# ==============================================================================
# 0. Bake 헬퍼
# ==============================================================================


def bake_geometry_to_layer(
    geometry_list: List[Any], layer_name: str, doc: Rhino.RhinoDoc
) -> None:
    """지정 레이어로 지오메트리 리스트를 Bake 합니다.

    레이어가 없으면 '::' 기준으로 상위-하위 레이어를 생성합니다.

    Args:
        geometry_list (List[Any]): Bake할 지오메트리 목록.
        layer_name (str): 대상 레이어 이름(전체 경로).
        doc (Rhino.RhinoDoc): 대상 문서.
    """
    try:
        if not geometry_list or not doc:
            return
        layer_index = _ensure_layer(doc, layer_name)
        if layer_index < 0:
            return
        success = 0
        total = len(geometry_list)
        for g in geometry_list:
            if _add_geometry(doc, g, layer_index):
                success += 1
        doc.Views.Redraw()
        debug_print("[bake] layer=", layer_name, "total=", total, "added=", success)
    except Exception:
        # 조용히 실패 허용 (GH 컴포넌트 안정성 우선)
        pass


# ==============================================================================
# 1. 데이터 입력 (Source Centerlines)
# ==============================================================================


def get_source_centerlines(doc: Rhino.RhinoDoc) -> List[Tuple[geo.Curve, float]]:
    """문서에서 Road::Centerline 하위 레이어의 중심선과 총 폭을 수집합니다.

    레이어명 형식: 'Road::Centerline::{TotalWidth}'

    Args:
        doc (Rhino.RhinoDoc): Rhino 문서.

    Returns:
        List[Tuple[geo.Curve, float]]: (중심선 커브, 도로 총 폭) 튜플 리스트.
    """
    results: List[Tuple[geo.Curve, float]] = []
    try:
        if doc is None:
            return results

        # 문서 공차 및 폴리라인 근사에 사용할 세그먼트 길이 결정
        tol = _get_model_tol(doc)
        default_seg_len = max(0.5, float(tol) * 10.0)

        parent_idx = doc.Layers.FindByFullPath(LAYER_SRC_CENTERLINE_PARENT, -1)
        parent_layer_id = None if parent_idx == -1 else doc.Layers[parent_idx].Id
        debug_print(
            "[source] parent=",
            LAYER_SRC_CENTERLINE_PARENT,
            "found_index=",
            parent_idx,
        )

        for layer in doc.Layers:
            try:
                # 부모 체크: 부모가 명시되어 있다면 ParentLayerId 매칭,
                # 아니면 FullPath 기반 접두사로 필터링
                if parent_layer_id:
                    if layer.ParentLayerId != parent_layer_id:
                        continue
                else:
                    full_path = getattr(layer, "FullPath", layer.Name)
                    if not full_path.startswith(LAYER_SRC_CENTERLINE_PARENT + "::"):
                        continue

                # 이름에서 총 폭 파싱
                full_path = getattr(layer, "FullPath", layer.Name)
                try:
                    total_width_str = full_path.split("::")[-1]
                    total_width = float(total_width_str)
                except Exception:
                    debug_print("[source] skip (parse fail):", full_path)
                    continue

                # 레이어의 커브 수집
                layer_objects = list(doc.Objects.FindByLayer(layer))
                if not layer_objects:
                    debug_print("[source] no objects:", full_path)
                    continue

                valid_found = False
                added_count = 0
                for obj_ref in layer_objects:
                    try:
                        geom = obj_ref.Geometry
                        if isinstance(geom, geo.Curve) and geom.IsValid:
                            # 커브를 폴리라인 근사로 변환하여 처리 (곡선에서 확장 이슈 방지)
                            poly_crv = None
                            try:
                                poly_crv = _to_polyline_curve(
                                    geom, default_seg_len, tol
                                )
                            except Exception:
                                poly_crv = None

                            if poly_crv and getattr(poly_crv, "IsValid", True):
                                print("SUCCEEDED POLY CONVERT")
                                results.append((poly_crv, total_width))
                                valid_found = True
                                added_count += 1
                                continue

                            # 폴리라인 변환이 실패하면 원본 커브의 복제본을 사용
                            try:
                                results.append((geom.DuplicateCurve(), total_width))
                                print("FAIL POLY CONVERT")
                                valid_found = True
                                added_count += 1
                            except Exception:
                                continue
                    except Exception:
                        continue

                if not valid_found:
                    # 유효 커브가 없으면 스킵
                    continue
                debug_print(
                    "[source] layer=",
                    full_path,
                    "total_width=",
                    total_width,
                    "curves_added=",
                    added_count,
                )
            except Exception:
                continue
    except Exception:
        return results

    return results


# ==============================================================================
# 2. 지오메트리 생성 헬퍼
# ==============================================================================


def _pick_offset_curve(curves: List[geo.Curve]) -> Optional[geo.Curve]:
    """Offset 결과 곡선 리스트에서 가장 적합한 하나를 선택합니다.

    기본 전략: 가장 긴 커브를 선택.
    """
    if not curves:
        return None
    try:
        curves = [c for c in curves if isinstance(c, geo.Curve) and c.IsValid]
        if not curves:
            return None
        curves.sort(key=lambda c: c.GetLength() if c.IsValid else 0.0, reverse=True)
        return curves[0]
    except Exception:
        return curves[0]


def _get_curve_plane(curve: geo.Curve) -> geo.Plane:
    """커브의 적절한 평면을 추정합니다. 실패 시 WorldXY."""
    try:
        ok, pl = curve.TryGetPlane()
        if ok:
            return pl
    except Exception:
        pass
    return geo.Plane.WorldXY


def _offset_curve(curve: geo.Curve, dist: float, tol: float) -> Optional[geo.Curve]:
    """커브를 주어진 거리만큼 오프셋한 결과 중 대표 커브를 반환합니다."""
    if not curve:
        return None
    if dist == 0.0:
        # 0 오프셋은 원 커브의 복제본을 반환하여 부작용을 피합니다.
        try:
            return curve.DuplicateCurve()
        except Exception:
            return curve
    try:
        plane = _get_curve_plane(curve)
        # RhinoCommon Offset은 List[Curve] 반환
        crvs = curve.Offset(plane, dist, tol, geo.CurveOffsetCornerStyle.Sharp)
        return _pick_offset_curve(list(crvs) if crvs else [])
    except Exception:
        # ghcomponents Offset 시도 (Polyline에 강함)
        try:
            res = ghcomp.OffsetCurve(curve, dist)
            if isinstance(res, list) and res:
                return _pick_offset_curve(res)
            if isinstance(res, geo.Curve):
                return res
        except Exception:
            pass
    return None


def _loft_between(curve_a: geo.Curve, curve_b: geo.Curve) -> Optional[geo.Surface]:
    """두 커브 사이를 Loft하여 Surface를 생성합니다.

    Returns:
        Optional[geo.Surface]: 성공 시 Surface, 실패 시 None.
    """
    try:
        breps = geo.Brep.CreateFromLoft(
            [curve_a, curve_b],
            geo.Point3d.Unset,
            geo.Point3d.Unset,
            geo.LoftType.Straight,
            False,
        )
        if breps:
            brep = breps[0]
            if brep and brep.Faces.Count > 0:
                return brep.Faces[0].DuplicateSurface()
    except Exception:
        pass

    # gh Loft 폴백
    try:
        loft_res = ghcomp.Loft([curve_a, curve_b])
        if isinstance(loft_res, list) and loft_res:
            brep = loft_res[0]
        else:
            brep = loft_res
        if isinstance(brep, geo.Brep) and brep.Faces.Count > 0:
            return brep.Faces[0].DuplicateSurface()
    except Exception:
        pass

    return None


def create_band_surface(
    center_curve: geo.Curve, dist_a: float, dist_b: float, tol: float
) -> Optional[geo.Surface]:
    """원본 중심선으로부터 두 거리 구간 [dist_a, dist_b] 사이의 띠(밴드) Surface 생성.

    dist_a, dist_b는 원본 중심선 기준의 오프셋 거리입니다. 예:
    - 단일 중앙선: [-w/2, +w/2]
    - 이중 중앙선(3차선 이상): [0, +w], [-w, 0]

    Args:
        center_curve (geo.Curve): 기준 중심선.
        dist_a (float): 첫 번째 오프셋 거리(원본 기준). 0이면 원 커브 사용.
        dist_b (float): 두 번째 오프셋 거리(원본 기준). 0이면 원 커브 사용.
        tol (float): 문서 공차.

    Returns:
        Optional[geo.Surface]: 생성된 Surface. 실패 시 None.
    """
    if not center_curve:
        return None

    try:
        crv_a = _offset_curve(center_curve, float(dist_a), tol)
        crv_b = _offset_curve(center_curve, float(dist_b), tol)
        if not crv_a or not crv_b:
            return None
        return _loft_between(crv_a, crv_b)
    except Exception:
        return None


def _to_polyline_curve(
    curve: geo.Curve, segment_length: float, tol: float
) -> Optional[geo.Curve]:
    """커브를 PolylineCurve로 안정적으로 근사합니다.

    - 과도한 세그먼트 길이로 인해 형태가 뻥튀기(과대)되는 문제를 줄이기 위해
      세그먼트 개수를 길이에 따라 적절히 제한/보정합니다.
    - 닫힌 커브의 경우 시작/끝 포인트 중복으로 긴 세그먼트가 생기지 않도록 처리합니다.

    Args:
        curve (geo.Curve): 입력 커브.
        segment_length (float): 목표 세그먼트 길이(상한/하한으로만 사용될 수 있음).
        tol (float): 문서 공차(포인트 비교 등 기준).

    Returns:
        Optional[geo.PolylineCurve]: 근사된 폴리라인 커브. 실패 시 원본 복제 또는 None.
    """
    if curve is None:
        return None

    try:
        # 이미 폴리라인이면 복제 반환
        if isinstance(curve, geo.PolylineCurve):
            return curve.DuplicateCurve()

        length = curve.GetLength()
        if not length or length <= 0.0:
            return curve.DuplicateCurve()

        # 샘플 개수 계산: 길이에 비례, 과소/과대 샘플링 방지
        # - segment_length가 크면 과도 단순화되어 offset 시 부풀어 보이는 문제 발생 가능
        # - 최소/최대 세그먼트 개수 클램핑으로 안정화
        base_seg_len = (
            float(segment_length)
            if segment_length and segment_length > 0
            else max(0.25, tol * 10.0)
        )
        est_count = max(2, int(math.ceil(length / base_seg_len)))
        count = max(32, min(est_count, 512))  # [32, 512]로 제한

        # 파라미터 샘플 (양 끝 포함)
        params = curve.DivideByCount(count, True)
        if not params or len(params) < 2:
            # DivideByLength 폴백
            params = curve.DivideByLength(base_seg_len, True)

        if not params:
            return curve.DuplicateCurve()

        # 포인트 생성
        pts = []
        for t in params:
            try:
                pts.append(curve.PointAt(float(t)))
            except Exception:
                continue

        if len(pts) < 2:
            return curve.DuplicateCurve()

        # 닫힌 커브 처리: 끝점을 시작점과 강제로 일치시켜 불필요한 장거리 세그먼트 방지
        is_closed = False
        try:
            is_closed = bool(curve.IsClosed)
        except Exception:
            is_closed = False

        if is_closed:
            # 첫/끝 점이 충분히 가까우면 끝 점을 첫 점으로 스냅
            if pts[0].DistanceTo(pts[-1]) <= max(tol, 1e-6):
                pts[-1] = geo.Point3d(pts[0])

        pl = geo.Polyline(pts)

        # 닫힌 상태 보정 (PolylineCurve에서 닫힘 성질 유지)
        try:
            if is_closed and not pl.IsClosed:
                pl.Add(pl[0])
        except Exception:
            pass

        if pl.IsValid:
            plc = geo.PolylineCurve(pl)
            if getattr(plc, "IsValid", False):
                return plc
    except Exception:
        pass

    # 최종 폴백: 원본 복제
    try:
        return curve.DuplicateCurve()
    except Exception:
        return None


def create_line_surface(
    center_curve: geo.Curve, line_width: float
) -> Optional[geo.Surface]:
    """중심 커브 기준으로 폭이 line_width인 선 도색 Surface를 생성합니다.

    center_curve를 양측으로 line_width/2만큼 오프셋해 서로를 Loft합니다.

    Args:
        center_curve (geo.Curve): 기준 커브.
        line_width (float): 선 폭.

    Returns:
        Optional[geo.Surface]: 생성된 Surface. 실패 시 None.
    """
    if center_curve is None or line_width is None or line_width <= 0.0:
        return None

    tol = _get_model_tol(sc.doc if hasattr(sc, "doc") else None)

    half = 0.5 * float(line_width)
    try:
        c1 = _offset_curve(center_curve, +half, tol)
        c2 = _offset_curve(center_curve, -half, tol)
        if not c1 or not c2:
            debug_print("[line] offset failed: half=", half)
            return None
        srf = _loft_between(c1, c2)
        if srf is None:
            debug_print("[line] loft failed")
        return srf
    except Exception:
        return None


def create_centerlines(
    centerline_curve: geo.Curve, num_lanes: int, line_width: float
) -> List[geo.Surface]:
    """중앙선 Surface 생성.

    - 2차선: 입력 커브에 대해 1개의 실선 Surface 생성.
    - 3차선 이상: 입력 커브를 line_width/2 만큼 좌우 오프셋한 두 커브 각각에 대해
      실선 Surface 생성하여 2개 반환.

    Args:
        centerline_curve (geo.Curve): 중심 커브.
        num_lanes (int): 차선 수.
        line_width (float): 선 폭.

    Returns:
        List[geo.Surface]: 생성된 중앙선 Surface 리스트.
    """
    out: List[geo.Surface] = []
    if not centerline_curve or num_lanes is None or line_width is None:
        return out
    if line_width <= 0.0:
        return out

    tol = _get_model_tol(sc.doc if hasattr(sc, "doc") else None)

    try:
        half = 0.5 * float(line_width)
        if num_lanes == 2:
            # 원본 중심선을 정확히 중심으로 하는 단일 밴드 [-w/2, +w/2]
            srf = create_band_surface(centerline_curve, -half, +half, tol)
            if srf:
                out.append(srf)
            debug_print("[centerline] lanes=2 surfaces=", len(out))
            return out

        if num_lanes > 2:
            # 원본 중심선과 정확히 일치하는 경계(중앙선)를 기준으로 좌/우 밴드 생성
            left_band = create_band_surface(
                centerline_curve, 0.0, float(line_width), tol
            )
            right_band = create_band_surface(
                centerline_curve, -float(line_width), 0.0, tol
            )
            for srf in (left_band, right_band):
                if srf:
                    out.append(srf)
            debug_print("[centerline] lanes=", num_lanes, "surfaces=", len(out))
    except Exception:
        return out

    return out


def create_lanelines(
    centerline_curve: geo.Curve,
    total_width: float,
    lane_width: float,
    line_width: float,
    num_lanes: int,
) -> List[geo.Surface]:
    """차선(Laneline) Surface들을 생성합니다.

    - 차선 수가 n이면 차선은 n-1개 생성.
    - 각 차선은 Paint(5m) + Gap(8m) 패턴으로 분절된 Surface들의 집합.

    Args:
        centerline_curve (geo.Curve): 기준 중심선 커브.
        total_width (float): 도로 총 폭.
        lane_width (float): 개별 차선 폭.
        line_width (float): 선 도색 폭.
        num_lanes (int): 차선 수.

    Returns:
        List[geo.Surface]: 생성된 차선 Surface 리스트.
    """
    out: List[geo.Surface] = []
    if (
        not centerline_curve
        or total_width is None
        or lane_width is None
        or line_width is None
        or num_lanes is None
    ):
        return out
    if lane_width <= 0.0 or line_width <= 0.0 or num_lanes < 2:
        return out

    tol = _get_model_tol(sc.doc if hasattr(sc, "doc") else None)
    segment_span = float(LANE_PAINT_LENGTH) + float(LANE_GAP_LENGTH)

    try:
        for i in range(1, int(num_lanes)):
            if i >= num_lanes:
                break
            # 기준선에서 i번째 차선 위치의 기준 커브 생성
            offset_dist = (i * lane_width) - (total_width * 0.5)
            lane_base = _offset_curve(centerline_curve, offset_dist, tol)
            if not lane_base:
                debug_print("[laneline] offset fail i=", i, "dist=", offset_dist)
                continue

            # 분절 기준 파라미터 획득 (각 주기 시작점들)
            params = lane_base.DivideByLength(segment_span, True)
            if not params:
                debug_print("[laneline] no params i=", i, "span=", segment_span)
                continue

            # 각 시작 파라미터에서 Paint 길이만큼 트림
            made_segments = 0
            for t in params:
                try:
                    # t에서부터 LANE_PAINT_LENGTH 만큼 떨어진 파라미터 계산
                    # 1) 시작까지의 누적 길이
                    dom = lane_base.Domain
                    length_to_t = lane_base.GetLength(geo.Interval(dom.Min, float(t)))
                    if length_to_t is None:
                        continue
                    target_from_start = float(length_to_t) + float(LANE_PAINT_LENGTH)

                    ok, t_end = lane_base.LengthParameter(target_from_start)
                    if not ok:
                        # 범위를 벗어나면 스킵
                        continue

                    seg = lane_base.Trim(float(t), float(t_end))
                    if not seg or not seg.IsValid:
                        continue

                    srf = create_line_surface(seg, line_width)
                    if srf:
                        out.append(srf)
                        made_segments += 1
                except Exception:
                    continue
            debug_print(
                "[laneline] i=", i, "params=", len(params), "segments=", made_segments
            )
    except Exception:
        return out

    debug_print("[laneline] total surfaces=", len(out))
    return out


ess_create_edgelines_doc = (
    """도로 가장자리 선은 도로 폭의 절반에서 선폭*2 만큼 안쪽으로 생성됩니다."""
)


def create_edgelines_from_regions(
    road_regions: List[geo.Curve], line_width: float, inset: Optional[float] = None
) -> List[geo.Surface]:
    """도로 영역(road_regions) 경계로부터 안쪽으로 inset만큼 오프셋한 경로를 기준으로 EdgeLine 생성.

    - 기존 방식(중심선 기준) 대신, 이미 생성된 도로 영역의 외곽 경계를 신뢰 소스로 사용합니다.
    - 각 경계 커브를 내부로 inset만큼 오프셋한 커브를 중심 커브로 삼아 폭 line_width의 띠 Surface를 만듭니다.

    Args:
        road_regions (List[geo.Curve]): 도로 영역 경계 커브 리스트(닫힌 커브 권장).
        line_width (float): EdgeLine의 폭.
        inset (Optional[float]): 외곽에서 내부로 떨어질 거리. 기본값은 2*line_width.

    Returns:
        List[geo.Surface]: 생성된 EdgeLine Surface 리스트.
    """
    out: List[geo.Surface] = []
    if not road_regions or line_width is None or line_width <= 0.0:
        return out

    tol = _get_model_tol(sc.doc if hasattr(sc, "doc") else None)
    d_inset = float(inset) if inset is not None else 2.0 * float(line_width)
    if d_inset <= 0.0:
        d_inset = 2.0 * float(line_width)

    try:
        for region in road_regions:
            if not isinstance(region, geo.Curve):
                continue
            if not getattr(region, "IsClosed", False):
                # 폐곡선이 아니면 스킵
                continue

            # 내부로 inset + (line_width/2)를 이동한 '중심 경로'를 만들고, 그 경로 기준 폭 line_width로 띠를 생성
            center_offset = d_inset + 0.5 * float(line_width)
            try:
                inner_paths = offset_regions_outward(
                    region, center_offset
                )  # from utils
            except Exception:
                inner_paths = None

            if not inner_paths:
                # 영역이 너무 좁아 오프셋 불가한 경우
                continue

            # 가장 긴 내부 경로를 대표로 선택
            try:
                inner_paths = [c for c in inner_paths if isinstance(c, geo.Curve)]
                inner_paths.sort(
                    key=lambda c: c.GetLength() if c.IsValid else 0.0, reverse=True
                )
            except Exception:
                pass

            for path in inner_paths:
                try:
                    if not path or not getattr(path, "IsValid", True):
                        continue
                    srf = create_line_surface(path, line_width)
                    if srf:
                        out.append(srf)
                except Exception:
                    continue
        debug_print("[edgeline] from regions: inset=", d_inset, "surfaces=", len(out))
    except Exception:
        return out

    return out


# ==============================================================================
# 3. 메인 실행 (Orchestrator)
# ==============================================================================


def run_road_builder(
    Run: bool, Bake: bool, lane_width: float, line_width: float
) -> Tuple[List[geo.Surface], List[geo.Surface], List[geo.Surface]]:
    """RoadDetailBuilder 오케스트레이터.

    Args:
        Run (bool): 실행 여부.
        Bake (bool): 결과 Bake 여부.
        lane_width (float): 차선 폭.
        line_width (float): 선 도색 폭.

    Returns:
        Tuple[List[geo.Surface], List[geo.Surface], List[geo.Surface]]: (center, lane, edge)
    """
    if not Run:
        return [], [], []
    if lane_width is None or line_width is None:
        return [], [], []
    if lane_width <= 0.0 or line_width <= 0.0:
        return [], [], []

    prev_doc = getattr(sc, "doc", None)
    try:
        sc.doc = Rhino.RhinoDoc.ActiveDoc
    except Exception:
        # GH 외부 환경 대비
        sc.doc = prev_doc

    try:
        source_data = get_source_centerlines(sc.doc)

        all_centerlines: List[geo.Surface] = []
        all_lanelines: List[geo.Surface] = []
        all_edgelines: List[geo.Surface] = []

        # 선택 입력: road_regions (GH에서 직접 입력되는 경우 우선 사용)
        try:
            rr_input = list(globals().get("road_regions", []))
        except Exception:
            rr_input = []

        debug_print(
            "[run] inputs:",
            {"lane_width": lane_width, "line_width": line_width, "Bake": Bake},
        )
        debug_print("[run] sources:", len(source_data))

        for center_crv, total_width in source_data:
            try:
                if total_width is None or lane_width <= 0.0:
                    continue
                num_lanes = int(round(float(total_width) / float(lane_width)))
                if num_lanes < 2:
                    continue

                # 생성
                cs = create_centerlines(center_crv, num_lanes, line_width)
                ls = create_lanelines(
                    center_crv, total_width, lane_width, line_width, num_lanes
                )
                # 에지라인: road_regions 입력이 없을 때만 기존 방식으로 생성 (중심선 기반)
                if not rr_input:
                    es_local: List[geo.Surface] = []
                    try:
                        tol_local = _get_model_tol(
                            sc.doc if hasattr(sc, "doc") else None
                        )
                        edge_offset = 0.5 * float(total_width)
                        inset_val = 2.0 * float(line_width)
                        final_offset = edge_offset - inset_val
                        if final_offset > 0.0:
                            left = _offset_curve(center_crv, +final_offset, tol_local)
                            right = _offset_curve(center_crv, -final_offset, tol_local)
                            for crv in (left, right):
                                if crv:
                                    srf = create_line_surface(crv, line_width)
                                    if srf:
                                        es_local.append(srf)
                    except Exception:
                        es_local = []
                    all_edgelines.extend(es_local)

                all_centerlines.extend(cs)
                all_lanelines.extend(ls)

                debug_print(
                    "[run] total_width=",
                    total_width,
                    "num_lanes=",
                    num_lanes,
                    "center=",
                    len(cs),
                    "lane=",
                    len(ls),
                    "edge=",
                    (len(es_local) if not rr_input else 0),
                )
            except Exception:
                continue

        # road_regions 입력이 있는 경우: 영역 기반으로 edgelines 생성 (기존 방식 대체)
        if rr_input:
            try:
                all_edgelines = create_edgelines_from_regions(
                    rr_input, line_width, inset=2.0 * float(line_width)
                )
            except Exception:
                pass

        if Bake and sc.doc is not None:
            try:
                bake_geometry_to_layer(all_centerlines, LAYER_BAKE_CENTERLINE, sc.doc)
                bake_geometry_to_layer(all_lanelines, LAYER_BAKE_LANELINE, sc.doc)
                bake_geometry_to_layer(all_edgelines, LAYER_BAKE_EDGELINE, sc.doc)
            except Exception:
                pass

        debug_print(
            "[run] result counts:",
            {
                "centerlines": len(all_centerlines),
                "lanelines": len(all_lanelines),
                "edgelines": len(all_edgelines),
            },
        )
        return all_centerlines, all_lanelines, all_edgelines
    finally:
        # 컨텍스트 복원 (GH 컴포넌트에서는 ghdoc가 prev_doc로 설정되어 있음)
        try:
            sc.doc = prev_doc
        except Exception:
            pass


# ==============================================================================
# 4. GH 컴포넌트 실행부 (입출력 바인딩)
# ==============================================================================
# 아래 코드는 Grasshopper Python 컴포넌트의 입력 변수를 가정합니다:
# - Run (bool), Bake (bool), lane_width (float), line_width (float)
# 출력:
# - centerlines, lanelines, edgelines
try:
    _Run = bool(globals().get("Run", False))
    _Bake = bool(globals().get("Bake", False))
    _lane_width = float(globals().get("lane_width", 0.0))
    _line_width = float(globals().get("line_width", 0.0))
    _DEBUG = bool(globals().get("Debug", True))

    if _DEBUG:
        debug_print(
            "[inputs] Run=",
            _Run,
            "Bake=",
            _Bake,
            "lane_width=",
            _lane_width,
            "line_width=",
            _line_width,
        )
    if _Run:
        centerlines, lanelines, edgelines = run_road_builder(
            _Run, _Bake, _lane_width, _line_width
        )
    else:
        centerlines, lanelines, edgelines = [], [], []
except Exception:
    # 컴포넌트 입력 미정의/외부 실행 대비
    centerlines, lanelines, edgelines = [], [], []
