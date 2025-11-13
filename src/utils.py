# -*- coding: utf-8 -*-
"""
프로젝트 전반에서 사용하는 Rhino/Grasshopper 공용 유틸리티입니다.

이 모듈은 특정 프로젝트 영역에 종속되지 않도록 설계되었습니다. 함수들은 '어디서 쓰이는지'가 아니라
'무엇을 하는지' 기준으로 분류되어, 어느 위치에서든 자유롭게 가져다 쓸 수 있습니다.

구성
- 코어 지오메트리: 거리/벡터/정점/기본 커브 연산
- 고급 지오메트리: 교차, 겹침, 영역 포함 관계
- 단순화: 폴리라인 계열 세그먼트 감소 기반 단순화
- 변환/윤곽: Brep 이동, 윤곽/법선 헬퍼
- 레이어/문서: 레이어 조회/생성/정리
- 서피스/Brep: Extrude, Face 샘플링, 평면 Face 재구성
"""
from typing import List, Tuple, Any, Optional, Union
import math
import functools
import Rhino
import Rhino.Geometry as geo
import ghpythonlib.components as ghcomp

from constants import TOL, ROUNDING_PRECISION, BIGNUM, OP_TOL, CLIPPER_TOL

# Type Hinting
CurveLike = Union[geo.Curve, List[geo.Curve]]


def convert_io_to_list(func):
    """단일 Curve 인/아웃을 리스트 형태로 표준화하는 데코레이터입니다.

    함수가 단일 Curve와 Curve 리스트를 모두 받아야 하고,
    반환도 일관된 리스트 형태로 맞추고 싶을 때 사용하세요.
    커브가 아닌 값은 그대로 통과합니다.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        new_args = []
        for arg in args:
            if isinstance(arg, geo.Curve):
                arg = [arg]
            new_args.append(arg)

        result = func(*new_args, **kwargs)
        if isinstance(result, geo.Curve):
            result = [result]
        if hasattr(result, "__dict__"):
            for key, values in result.__dict__.items():
                if isinstance(values, geo.Curve):
                    setattr(result, key, [values])
        return result

    return wrapper


# ==============================================================================
# 1. 코어 지오메트리 유틸리티 (Core Geometry Utilities)
# ==============================================================================


def get_distance_between_points(point_a: geo.Point3d, point_b: geo.Point3d) -> float:
    """두 점 사이의 거리를 계산합니다."""
    return round(point_a.DistanceTo(point_b), ROUNDING_PRECISION)


def get_distance_between_point_and_curve(point: geo.Point3d, curve: geo.Curve) -> float:
    """점과 커브 사이의 최단 거리를 계산합니다."""
    _, param = curve.ClosestPoint(point)
    dist = point.DistanceTo(curve.PointAt(param))
    return round(dist, ROUNDING_PRECISION)


def get_distance_between_curves(curve_a: geo.Curve, curve_b: geo.Curve) -> float:
    """두 커브 사이의 최소 거리를 계산합니다."""
    _, pt_a, pt_b = curve_a.ClosestPoints(curve_b)
    dist = pt_a.DistanceTo(pt_b)
    return round(dist, ROUNDING_PRECISION)


def get_vector_from_pts(pt_a: geo.Point3d, pt_b: geo.Point3d) -> geo.Vector3d:
    """두 점 사이의 벡터를 계산합니다."""
    return geo.Vector3d(pt_b.X - pt_a.X, pt_b.Y - pt_a.Y, pt_b.Z - pt_a.Z)


def get_vertices(curve: geo.Curve) -> List[geo.Point3d]:
    """커브의 모든 정점(Vertex)들을 추출합니다."""
    if not curve:
        return []
    vertices = [curve.PointAt(curve.SpanDomain(i)[0]) for i in range(curve.SpanCount)]
    if not curve.IsClosed:
        vertices.append(curve.PointAtEnd)
    return vertices


def move_curve(curve: geo.Curve, vector: geo.Vector3d) -> geo.Curve:
    """커브를 주어진 벡터만큼 이동시킨 복사본을 반환합니다."""
    moved_curve = curve.Duplicate()
    moved_curve.Translate(vector)
    return moved_curve


def explode_curve(curve: geo.Curve) -> List[geo.Curve]:
    """커브를 분할하여 개별 세그먼트 리스트로 반환합니다."""
    if not curve:
        return []
    if isinstance(curve, geo.PolyCurve):
        return list(curve.DuplicateSegments())

    segments = []
    if curve.SpanCount > 0:
        for i in range(curve.SpanCount):
            sub_curve = curve.Trim(curve.SpanDomain(i))
            if sub_curve:
                segments.append(sub_curve)
    elif curve.IsLinear():
        segments.append(curve.Duplicate())

    return segments


def get_pts_by_length(
    crv: geo.Curve, length: float, include_start: bool = False
) -> List[geo.Point3d]:
    """커브를 주어진 길이로 나누는 점들을 구합니다."""
    params = crv.DivideByLength(length, include_start)
    if not params:
        return []
    return [crv.PointAt(param) for param in params]


def get_area(regions: Union[List[geo.Curve], geo.Curve]) -> float:
    """영역 커브의 면적을 계산합니다."""
    if not isinstance(regions, list):
        regions = [regions]

    area = sum([geo.AreaMassProperties.Compute(r).Area for r in regions])
    return round(area, ROUNDING_PRECISION)


# ==============================================================================
# 2. 고급 지오메트리 연산 (Advanced Geometry Operations)
# ==============================================================================


def has_intersection(
    curve_a: geo.Curve,
    curve_b: geo.Curve,
    plane: geo.Plane = geo.Plane.WorldXY,
    tol: float = TOL,
) -> bool:
    """두 커브가 교차하는지 여부를 확인합니다."""
    return geo.Curve.PlanarCurveCollision(curve_a, curve_b, plane, tol)


def get_intersection_points(
    curve_a: geo.Curve, curve_b: geo.Curve, tol: float = TOL
) -> List[geo.Point3d]:
    """두 커브 사이의 교차점을 계산합니다."""
    intersections = geo.Intersect.Intersection.CurveCurve(curve_a, curve_b, tol, tol)
    if not intersections:
        return []
    return [event.PointA for event in intersections if event.IsPointAValid]


def has_region_intersection(
    region_a: geo.Curve, region_b: geo.Curve, tol: float = TOL
) -> bool:
    """두 닫힌 영역 커브가 교차(겹침 포함)하는지 확인합니다."""
    relationship = geo.Curve.PlanarClosedCurveRelationship(
        region_a, region_b, geo.Plane.WorldXY, tol
    )
    return relationship != geo.RegionContainment.Disjoint


def is_region_inside(
    inner_region: geo.Curve, outer_region: geo.Curve, tol: float = TOL
) -> bool:
    """내부 영역이 외부 영역에 포함되는지 확인합니다."""
    relationship = geo.Curve.PlanarClosedCurveRelationship(
        inner_region, outer_region, geo.Plane.WorldXY, tol
    )

    return relationship == geo.RegionContainment.AInsideB


def get_overlapped_curves(curve_a: geo.Curve, curve_b: geo.Curve) -> List[geo.Curve]:
    """두 커브가 겹치는 구간의 커브들을 반환합니다."""
    if not has_intersection(curve_a, curve_b) or not ghcomp:
        return []

    intersection_points = get_intersection_points(curve_a, curve_b)
    explode_result = ghcomp.Explode(curve_a, True)
    explode_points = (
        explode_result.vertices + intersection_points
        if explode_result
        else intersection_points
    )

    if not explode_points:
        return []

    params = [ghcomp.CurveClosestPoint(pt, curve_a).parameter for pt in explode_points]
    shatter_result = ghcomp.Shatter(curve_a, params)

    if not shatter_result:
        return []

    overlapped_segments = [
        seg for seg in shatter_result if has_intersection(seg, curve_b)
    ]
    if not overlapped_segments:
        return []

    return geo.Curve.JoinCurves(overlapped_segments)


def get_overlapped_length(curve_a: geo.Curve, curve_b: geo.Curve) -> float:
    """두 커브가 겹치는 총 길이를 계산합니다."""
    overlapped_curves = get_overlapped_curves(curve_a, curve_b)
    if not overlapped_curves:
        return 0.0
    return sum(crv.GetLength() for crv in overlapped_curves)


class Offset:
    class _OffsetResult:
        def __init__(self):
            self.contour: Optional[List[geo.Curve]] = None
            self.holes: Optional[List[geo.Curve]] = None

    @convert_io_to_list
    def polyline_offset(
        self,
        crvs: List[geo.Curve],
        dists: List[float],
        miter: int = BIGNUM,
        closed_fillet: int = 2,
        open_fillet: int = 2,
        tol: float = Rhino.RhinoMath.ZeroTolerance,
    ) -> _OffsetResult:
        """Clipper 컴포넌트를 이용한 폴리라인 오프셋.

        입력 폴리라인(유사) 커브를 2D 평면에서 오프셋하고,
        바깥 윤곽(contour)과 내부 공백(holes)을 각각의 리스트로 반환합니다.

        Args:
            crvs (List[geo.Curve]): 오프셋할(폴리라인 호환) 커브들.
            dists (List[float]): 오프셋 거리. 양수는 바깥 윤곽을 생성하며,
                대응되는 안쪽 결과는 holes에 위치합니다.
            miter (int): 날카로운 코너를 위한 마이터 제한.
            closed_fillet (int): 닫힌 형태의 코너 스타일
                (0=round, 1=square, 2=miter).
            open_fillet (int): 열린 세그먼트의 끝 처리
                (0=round, 1=square, 2=butt).
            tol (float): 연산에 사용할 공차.

        Returns:
            Offset._OffsetResult: 다음 필드를 포함합니다.
                - contour: List[Curve] 바깥쪽 오프셋 결과
                - holes: List[Curve] 안쪽 오프셋 결과
        """
        if not crvs:
            raise ValueError("No Curves to offset")

        plane = geo.Plane(geo.Point3d(0, 0, crvs[0].PointAtEnd.Z), geo.Vector3d.ZAxis)
        result = ghcomp.ClipperComponents.PolylineOffset(
            crvs,
            dists,
            plane,
            tol,
            closed_fillet,
            open_fillet,
            miter,
        )

        polyline_offset_result = Offset._OffsetResult()
        for name in ("contour", "holes"):
            setattr(polyline_offset_result, name, result[name])
        return polyline_offset_result


def offset_regions_inward(
    regions: Union[geo.Curve, List[geo.Curve]], dist: float, miter: int = BIGNUM
) -> List[geo.Curve]:
    """영역 커브를 안쪽으로 offset 한다.
    단일커브나 커브리스트 관계없이 커브 리스트로 리턴한다.
    Args:
        region: offset할 대상 커브
        dist: offset할 거리

    Returns:
        offset 후 커브
    """

    if not dist:
        return regions
    result = Offset().polyline_offset(regions, dist, miter).holes

    if not result:
        return []

    if isinstance(regions, geo.Curve):
        regions = [regions]

    if len(result) < 2:
        return result

    filtered = [
        crv for crv in result if any(is_region_inside(crv, reg) for reg in regions)
    ]
    return filtered


def offset_regions_outward(
    regions: Union[geo.Curve, List[geo.Curve]], dist: float, miter: int = BIGNUM
) -> List[geo.Curve]:
    """영역 커브를 바깥쪽으로 offset 한다.
    단일커브나 커브리스트 관계없이 커브 리스트로 리턴한다.
    Args:
        region: offset할 대상 커브
        dist: offset할 거리
    returns:
        offset 후 커브
    """
    if isinstance(regions, geo.Curve):
        regions = [regions]

    return [offset_region_outward(region, dist, miter) for region in regions]


def simplify_regions_with_offset(
    regions: List[geo.Curve], dist: float, miter: int = BIGNUM
) -> Union[List[geo.Curve], geo.Curve]:
    """영역 커브를 안팎으로 offset 하여 단순화한다.
    이로인해 dist 미만의 폭을 가진 영역이 사라진다.
    Args:
        region: 단순화할 대상 커브
        dist: 안팎으로 offset할 거리

    Returns:
        단순화된 커브 리스트
    """
    if not regions:
        return []

    if dist <= 0.0:
        return regions

    inner = offset_regions_inward(regions, dist * 0.5, miter)
    if not inner:
        return []

    outer = offset_regions_outward(inner, dist * 0.5, miter)

    return outer


# ==============================================================================
# 2.1 폴리라인 기반 세그먼트 감소형 Simplify (전처리 친화)
# ==============================================================================


def simplify_crv_by_reducing_segments(
    crv: geo.Curve,
    tol: float = TOL,
    angle_tol: Optional[float] = None,
) -> geo.Curve:
    """MergeColinearSegments + ReduceSegments 기반 단순화.

    - colinear(동일선상) 세그먼트 병합 후, 길이/변화가 tol 이내인 세그먼트 제거로 안정화.
    - 닫힌 커브의 시작/끝 점 처리 보정 포함.
    - 실패/과도 단순화 시 원본 반환.
    """
    if crv is None:
        return crv

    if angle_tol is None:
        # 가능하면 constants.ANGLE_TOL 사용, 없으면 약 1도(라디안)
        try:
            from constants import ANGLE_TOL as _ANGLE_TOL  # type: ignore

            angle_tol = float(_ANGLE_TOL)
        except Exception:
            angle_tol = math.radians(1.0)

    # vertices 기반 polyline 작성
    pts = get_vertices(crv)
    if not pts:
        return crv
    if crv.IsClosed:
        pts.append(pts[0])

    pl = geo.Polyline(pts)

    # colinear 병합 및 세그먼트 감소
    try:
        pl.MergeColinearSegments(angle_tol, True)
    except Exception:
        pass
    try:
        pl.ReduceSegments(tol)
    except Exception:
        pass

    # 닫힌 커브의 시작점 보정(일부 케이스에서 ReduceSegments가 시작점에 동작하지 않음)
    try:
        if pl.IsClosed and pl.Count > 3:
            pt_items = list(pl.Item)
            pt_first = pt_items[0]
            pt1 = pt_items[1]
            pt2 = pt_items[pl.Count - 2]
            if geo.Line(pt1, pt2).DistanceTo(pt_first, True) <= tol:
                pl.RemoveAt(0)
                pl.RemoveAt(pl.Count - 1)
                pl.Add(pl.First)
    except Exception:
        pass

    polycrv = pl.ToPolylineCurve()
    if not getattr(polycrv, "IsValid", False):
        # 너무 작은/불안정한 경우 원본 유지
        return crv
    return polycrv


def simplify_crvs_by_reducing_segments(
    crvs: List[geo.Curve], tol: float = TOL, angle_tol: Optional[float] = None
) -> List[geo.Curve]:
    """여러 커브에 대해 세그먼트 감소형 단순화를 일괄 적용"""
    if not crvs:
        return []
    out: List[geo.Curve] = []
    for r in crvs:
        try:
            out.append(simplify_crv_by_reducing_segments(r, tol, angle_tol))
        except Exception:
            out.append(r)
    return out


def offset_region_outward(
    region: geo.Curve, dist: float, miter: float = BIGNUM
) -> geo.Curve:
    """영역 커브를 바깥쪽으로 offset 한다.
    단일 커브를 받아서 단일 커브로 리턴한다.
    Args:
        region: offset할 대상 커브
        dist: offset할 거리

    Returns:
        offset 후 커브
    """

    if not dist:
        return region
    if not isinstance(region, geo.Curve):
        raise ValueError("region must be curve")
    return Offset().polyline_offset(region, dist, miter).contour[0]


class RegionBool:
    @convert_io_to_list
    def _polyline_boolean(
        self, crvs0, crvs1, boolean_type=None, plane=None, tol=CLIPPER_TOL
    ):
        """Clipper 기반 폴리라인 불리언 연산을 래핑하는 내부 헬퍼입니다.

        boolean_type: 0=교집합, 1=합집합, 2=차집합.
        결과 커브 리스트를 반환합니다(결과가 없으면 빈 리스트).
        """
        # type: (List[geo.Curve], List[geo.Curve], int, geo.Plane, float) -> List[geo.Curve]
        if not crvs0 or not crvs1:
            raise ValueError("Check input values")
        result = ghcomp.ClipperComponents.PolylineBoolean(
            crvs0, crvs1, boolean_type, plane, tol
        )

        # 결과는 IronPython.Runtime.List (파이썬 list처럼 동작) 이거나 단일 커브일 수 있으므로 통일해서 list로 반환
        if not result:
            return []

        # IronPython.Runtime.List, System.Collections.Generic.List, tuple 등 반복 가능한 결과를 모두 처리
        if isinstance(result, geo.Curve):
            # 단일 커브 객체
            result = [result]
        else:
            try:
                # IEnumerable / IronPython.Runtime.List / tuple / System.Collections.Generic.List 모두 list() 시도로 통일
                result = [crv for crv in list(result) if crv]
            except TypeError:
                # 반복 불가능한 단일 객체인 예외 상황
                result = [result]

        return result

    def polyline_boolean_intersection(self, crvs0, crvs1, plane=None, tol=CLIPPER_TOL):
        # type: (Union[geo.Curve, List[geo.Curve]], Union[geo.Curve, List[geo.Curve]], geo.Plane, float) -> List[geo.Curve]
        return self._polyline_boolean(crvs0, crvs1, 0, plane, tol)

    def polyline_boolean_union(self, crvs0, crvs1, plane=None, tol=CLIPPER_TOL):
        # type: (Union[geo.Curve, List[geo.Curve]], Union[geo.Curve, List[geo.Curve]], geo.Plane, float) -> List[geo.Curve]
        return self._polyline_boolean(crvs0, crvs1, 1, plane, tol)

    def polyline_boolean_difference(self, crvs0, crvs1, plane=None, tol=CLIPPER_TOL):
        # type: (Union[geo.Curve, List[geo.Curve]], Union[geo.Curve, List[geo.Curve]], geo.Plane, float) -> List[geo.Curve]
        return self._polyline_boolean(crvs0, crvs1, 2, plane, tol)


def get_intersection_regions(
    regions_a: List[geo.Curve], regions_b: List[geo.Curve]
) -> List[geo.Curve]:
    """두 영역 커브 리스트의 교집합을 구합니다.
    Args:
        regions_a: 첫 번째 영역 커브 리스트
        regions_b: 두 번째 영역 커브 리스트
    Returns:
        교집합 결과 커브들
    """
    if not regions_a or not regions_b:
        return []
    intersection_result = RegionBool().polyline_boolean_intersection(
        regions_a, regions_b
    )
    return intersection_result


def get_union_regions(regions: List[geo.Curve] = None) -> List[geo.Curve]:
    """주어진 영역 커브들의 합집합을 구합니다.
    Args:
        regions: 합집합을 구할 영역 커브들
    Returns:
        합집합 결과 커브들
    """
    if not regions:
        return []

    if len(regions) == 1:
        return regions

    union_result = list(geo.Curve.CreateBooleanUnion(regions, TOL))
    if union_result:
        return union_result

    union_result = regions[0]
    for region in regions[1:]:
        union_result = RegionBool().polyline_boolean_union(union_result, region)

    if not isinstance(union_result, list):
        union_result = [union_result]

    return union_result


# ============================================================================
# 3. 변환/문서/레이어 유틸리티 (project-agnostic)
# ============================================================================


def move_brep(brep: geo.Brep, vector: geo.Vector3d) -> geo.Brep:
    """Brep를 주어진 벡터만큼 이동시킨 복사본을 반환합니다.

    Args:
        brep (geo.Brep): 이동할 원본 Brep.
        vector (geo.Vector3d): 이동 벡터.

    Returns:
        geo.Brep: 이동된 Brep 복사본.
    """
    moved_brep = brep.Duplicate()
    moved_brep.Translate(vector)
    return moved_brep


def get_outside_perp_vec_from_pt(pt: geo.Point3d, region: geo.Curve) -> geo.Vector3d:
    """영역 커브에서 특정 점의 외곽 방향 수직 벡터를 반환합니다.

    Args:
        pt (geo.Point3d): 기준 점.
        region (geo.Curve): 기준 영역 커브(닫힌 커브 권장).

    Returns:
        geo.Vector3d: 외곽 방향 법선 벡터.
    """
    _, param = region.ClosestPoint(pt)
    vec_perp_outer = region.PerpendicularFrameAt(param)[1].XAxis
    # 시계/반시계 방향에 따라 외곽 방향 부호 보정
    if region.ClosedCurveOrientation() != geo.CurveOrientation.Clockwise:
        vec_perp_outer = -vec_perp_outer
    return vec_perp_outer


def get_outline_from_closed_brep(
    brep: geo.Brep, plane: geo.Plane
) -> Optional[geo.Curve]:
    """닫힌 폴리서페이스(Brep)의 투영 윤곽선(가장 낮은 Z)을 반환합니다.

    Args:
        brep (geo.Brep): 닫힌 Brep.
        plane (geo.Plane): 기준 평면.

    Returns:
        Optional[geo.Curve]: 윤곽 PolylineCurve, 실패 시 None.
    """
    if not isinstance(brep, geo.Brep) or not getattr(brep, "IsSolid", False):
        raise TypeError("입력은 닫힌 Brep(폴리서페이스)만 허용됩니다.")
    bbox = brep.GetBoundingBox(True)
    contour_start = geo.Point3d(0, 0, bbox.Min.Z)
    contour_end = geo.Point3d(0, 0, bbox.Max.Z)
    curves = geo.Brep.CreateContourCurves(
        brep, contour_start, contour_end, (bbox.Max.Z - bbox.Min.Z)
    )
    if not curves:
        return None

    def _avg_z(curve: geo.Curve) -> float:
        return curve.PointAtStart.Z

    return min(curves, key=_avg_z)


# ============================================================================
# 4. Surface/Brep 유틸리티
# ============================================================================


def extrude_srf(srf: geo.Surface, height: float) -> Optional[geo.Brep]:
    """Surface/Brep를 z축 방향으로 height만큼 Extrude한 Brep을 반환합니다.

    Args:
        srf (geo.Surface|geo.Brep): 입력 서피스/Brep.
        height (float): 압출 높이.

    Returns:
        Optional[geo.Brep]: 캡 처리된 Brep. 실패 시 None.
    """
    try:
        extrusion = ghcomp.Extrude(srf, geo.Vector3d(0, 0, height))
        return ghcomp.CapHoles(extrusion)
    except Exception:
        return None


def is_point_on_srf(pt: geo.Point3d, srf: geo.Surface, tol: float = TOL) -> bool:
    """점이 서피스 위에 있는지 근사적으로 판정합니다.

    Args:
        pt (geo.Point3d): 테스트할 점.
        srf (geo.Surface): 대상 서피스.
        tol (float): 허용 오차.

    Returns:
        bool: 서피스 위에 있으면 True.
    """
    try:
        pt_on_srf = ghcomp.SurfaceClosestPoint(pt, srf).point
        return pt_on_srf.DistanceTo(pt) < max(0.01, tol)
    except Exception:
        return False


def get_point_inside_face(face: geo.BrepFace) -> Optional[geo.Point3d]:
    """BrepFace의 내부 임의 점(삼각형 무게중심 기반)을 반환합니다.

    Args:
        face (geo.BrepFace): 대상 Face.

    Returns:
        Optional[geo.Point3d]: 내부 점. 실패 시 None.
    """
    try:
        meshes = geo.Mesh.CreateFromBrep(face.Brep, geo.MeshingParameters.Default)
        if not meshes:
            return None
        mesh = meshes[0]
        idx = mesh.Faces[0]
        p0 = mesh.Vertices[idx.A]
        p1 = mesh.Vertices[idx.B]
        p2 = mesh.Vertices[idx.C]
        return geo.Point3d(
            (p0.X + p1.X + p2.X) / 3.0,
            (p0.Y + p1.Y + p2.Y) / 3.0,
            (p0.Z + p1.Z + p2.Z) / 3.0,
        )
    except Exception:
        return None


def get_layer_surfaces(doc: Rhino.RhinoDoc, parent_name: str) -> dict:
    """부모 레이어 아래의 각 자식 레이어에서 Surface/Brep 객체를 수집합니다.

    Args:
        doc (Rhino.RhinoDoc): Rhino 문서 객체.
        parent_name (str): 부모 레이어 이름.

    Returns:
        dict: {자식레이어명: [Brep, ...]} 매핑.
    """
    layer_dict = {}
    for layer in doc.Layers:
        if not layer.IsVisible:
            continue
        full_path = getattr(layer, "FullPath", layer.Name)
        parts = full_path.split("::") if full_path else []
        if len(parts) >= 2 and parts[0] == parent_name:
            child_name = parts[1]
            objs = list(doc.Objects.FindByLayer(layer))
            srfs = []
            for obj in objs:
                geo_obj = obj.Geometry
                if isinstance(geo_obj, geo.Surface):
                    srfs.append(geo.Brep.CreateFromSurface(geo_obj))
                elif isinstance(geo_obj, geo.Brep):
                    srfs.append(geo_obj)
            layer_dict.setdefault(child_name, []).extend(srfs)
    return layer_dict


def find_layer_by_fullpath(doc: Rhino.RhinoDoc, fullpath: str):
    """FullPath 문자열(예: "Parent::Child")로 레이어를 찾습니다."""
    for ly in doc.Layers:
        fp = getattr(ly, "FullPath", None) or ly.Name or ""
        if fp == fullpath:
            return ly
    return None


def ensure_layer(doc: Rhino.RhinoDoc, name: str, parent_id=None):
    """레이어가 존재하도록 보장합니다(필요 시 생성; 선택적으로 부모 아래 생성).

    기존 또는 새 레이어 객체를 반환합니다.
    """
    import System

    if parent_id:
        parent = doc.Layers.FindId(parent_id)
        parent_path = getattr(parent, "FullPath", parent.Name) if parent else None
        target_path = (parent_path + "::" + name) if parent_path else name
        found = find_layer_by_fullpath(doc, target_path)
        if found:
            return found
    else:
        for ly in doc.Layers:
            if ly.ParentLayerId == System.Guid.Empty and ly.Name == name:
                return ly

    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    if parent_id:
        layer.ParentLayerId = parent_id
        try:
            parent_layer = doc.Layers.FindId(parent_id)
            if parent_layer:
                layer.Color = parent_layer.Color
        except Exception:
            pass
    idx = doc.Layers.Add(layer)
    return doc.Layers[idx] if idx >= 0 else None


def clear_layer_tree(doc: Rhino.RhinoDoc, parent_name: str) -> int:
    """지정한 최상위 부모 레이어 트리(부모 포함) 아래의 모든 객체를 삭제합니다.

    Returns:
        int: 삭제된 객체 수.
    """
    import System

    parent = None
    for ly in doc.Layers:
        if ly.Name == parent_name and (ly.ParentLayerId == System.Guid.Empty):
            parent = ly
            break
    if not parent:
        return 0
    parent_path = getattr(parent, "FullPath", None) or parent.Name or ""
    deleted = 0
    for ly in doc.Layers:
        fp = getattr(ly, "FullPath", None) or ly.Name or ""
        if parent_path and (fp == parent_path or fp.startswith(parent_path + "::")):
            objs = doc.Objects.FindByLayer(ly) or []
            for obj in objs:
                if doc.Objects.Delete(obj, True):
                    deleted += 1
    return deleted


def planar_breps_from_face(
    doc: Rhino.RhinoDoc, face: geo.BrepFace, tol: float = TOL
) -> List[geo.Brep]:
    """하나의 BrepFace에서 평면 Brep들을 신뢰성 있게 재구성합니다.

    전략:
    1) 먼저 DuplicateFace(True)을 시도합니다.
    2) 실패 시 루프를 3D 커브로 변환해 CreatePlanarBreps를 수행합니다.
    """
    breps: List[geo.Brep] = []
    try:
        fb = face.DuplicateFace(True)
        if fb and fb.IsValid:
            breps.append(fb)
    except Exception:
        fb = None
    if not breps:
        try:
            crvs: List[geo.Curve] = []
            for loop in face.Loops:
                try:
                    crv = loop.To3dCurve()
                    if crv and crv.IsClosed:
                        crvs.append(crv)
                except Exception:
                    pass
            if crvs:
                made = geo.Brep.CreatePlanarBreps(crvs, tol)
                if made:
                    breps.extend([b for b in made if b and b.IsValid])
        except Exception:
            pass
    return breps


# Backward-compat alias (legacy name)
is_region_inside_region = is_region_inside
