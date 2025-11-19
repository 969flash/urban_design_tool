# -*- coding: utf-8 -*-
"""pedestrian_generator main entry for Grasshopper (Rhino 8 / Python 3).

본 스크립트는 landuse_calculator의 결과물인 Block을 읽어 보행로영역과 보행로에 들어갈 디테일 요소
(가로등, 가로수, 보행로가구)를 생성합니다. utils.py의 컨벤션(타입 힌트,
Google 스타일 Docstring, snake_case, geo 별칭)을 따릅니다.

주의:
- Grasshopper Python 3 컴포넌트에서 실행을 가정합니다.
"""

from typing import List, Tuple, Optional, Union, Any
import math

import Rhino
import Rhino.Geometry as geo
import scriptcontext as sc
import ghpythonlib.components as ghcomp
import System

# constants.py의 모든 상수 임포트 (단일 소스 관리)
import constants as CONST  # use module reference for reloading and direct access
import importlib

try:
    # Reload to pick up edits during GH iterations
    CONST = importlib.reload(CONST)
except Exception:
    # Safe to proceed with whatever was already loaded
    pass

# 프로젝트 유틸 전부 임포트
from utils import *  # noqa: F401,F403

# from landuse_calculator import Block


# =============================
# GH inputs and driver
# =============================
doc = Rhino.RhinoDoc.ActiveDoc

# Grasshopper inputs (with defaults)
RUN = bool(globals().get("Run", False))
BAKE = bool(globals().get("Bake", False))
BLOCKS = list(globals().get("blocks", []) or [])  # List[geo.Brep]
EXCLUDE_LANDUSES = list(globals().get("exclude_landuses", ["Green"]) or ["Green"])  # type: ignore

# Constants are referenced directly via CONST after reload


def _dprint(*args):
    try:
        print(*args)
    except Exception:
        pass


def _outer_boundary_from_region(brep):
    """Try to get a single closed outer boundary curve from a planar region Brep."""
    if not isinstance(brep, geo.Brep):
        return None
    # Prefer planar face outer loop
    try:
        for f in brep.Faces:
            if f.IsPlanar():
                crv = f.OuterLoop.To3dCurve()
                if crv and crv.IsClosed:
                    return crv
    except Exception:
        pass
    # Fallback: join naked edge curves
    try:
        edges = brep.DuplicateNakedEdgeCurves(True, False)
        joined = geo.Curve.JoinCurves(edges, TOL)
        if joined:
            for c in joined:
                if c and c.IsClosed:
                    return c
    except Exception:
        pass
    return None


def _planar_of_curve(crv):
    pl = geo.Plane.WorldXY
    try:
        ok, pl = crv.TryGetPlane()
        if ok:
            return pl
    except Exception:
        pass
    return pl


def _curve_area(crv):
    try:
        mp = geo.AreaMassProperties.Compute(crv)
        return float(mp.Area) if mp else 0.0
    except Exception:
        return 0.0


def _offset_inward(curv, dist):
    if not curv or dist <= 0:
        return None
    pl = _planar_of_curve(curv)
    tol = getattr(Rhino.RhinoDoc.ActiveDoc, "ModelAbsoluteTolerance", TOL)
    a0 = _curve_area(curv)
    try:
        cands = curv.Offset(pl, -abs(dist), tol, geo.CurveOffsetCornerStyle.Sharp)
        if not cands or len(cands) == 0:
            cands = curv.Offset(pl, abs(dist), tol, geo.CurveOffsetCornerStyle.Sharp)
        if not cands:
            return None
        # choose candidate with smallest area relative to original (inner)
        best = None
        best_area = None
        for c in cands:
            if not c or not c.IsClosed:
                continue
            a = _curve_area(c)
            if a <= 0:
                continue
            score = abs(a0 - a)
            if (best is None) or (score < best_area):
                best = c
                best_area = score
        return best
    except Exception:
        return None


def _create_planar_ring(outer_crv, inner_crv):
    """Create a planar donut-shaped Brep between outer and inner (hole)."""
    if not outer_crv or not inner_crv:
        return None
    tol = getattr(Rhino.RhinoDoc.ActiveDoc, "ModelAbsoluteTolerance", TOL)
    crvs = [outer_crv.DuplicateCurve(), inner_crv.DuplicateCurve()]
    try:
        breps = geo.Brep.CreatePlanarBreps(crvs, tol)
        if breps and len(breps) > 0:
            # CreatePlanarBreps may produce two surfaces; prefer one with hole
            # Pick the one with area close to outer - inner
            tgt_area = max(0.0, _curve_area(outer_crv) - _curve_area(inner_crv))
            best = None
            best_delta = None
            for b in breps:
                try:
                    mp = geo.AreaMassProperties.Compute(b)
                    if not mp:
                        continue
                    delta = abs(mp.Area - tgt_area)
                    if best is None or delta < best_delta:
                        best = b
                        best_delta = delta
                except Exception:
                    pass
            return best
    except Exception:
        pass
    # Fallback: boolean difference of regions
    try:
        outer_b = geo.Brep.CreatePlanarBreps([outer_crv], tol)
        inner_b = geo.Brep.CreatePlanarBreps([inner_crv], tol)
        if outer_b and inner_b:
            diff = geo.Brep.CreateBooleanDifference(outer_b[0], inner_b[0], tol)
            if diff and len(diff) > 0:
                return diff[0]
    except Exception:
        pass
    return None


def _make_box_brep(width, depth, height):
    """Make a box Brep centered in X/Y and starting at Z=0 (bottom at 0)."""
    try:
        x = float(width)
        y = float(depth)
        z = float(height)
        base = geo.Plane.WorldXY
        x_interval = Rhino.Geometry.Interval(-x * 0.5, x * 0.5)
        y_interval = Rhino.Geometry.Interval(-y * 0.5, y * 0.5)
        z_interval = Rhino.Geometry.Interval(0.0, z)
        box = geo.Box(base, x_interval, y_interval, z_interval)
        return box.ToBrep()
    except Exception:
        return None


def _ensure_block_def(doc, name, size_tuple):
    """Ensure a block (instance definition) exists, or create from box size.

    Base point is (0,0,0) which is bottom center of the box.
    """
    idefs = doc.InstanceDefinitions
    existing = idefs.Find(name, True)
    # If definition exists, return its index
    try:
        if existing is not None and getattr(existing, "Index", -1) >= 0:
            return int(existing.Index)
    except Exception:
        pass
    geom = []
    attr = []
    # Create box brep
    box = _make_box_brep(*size_tuple)
    if box:
        geom.append(box)
        attr.append(Rhino.DocObjects.ObjectAttributes())
    base_pt = geo.Point3d(0, 0, 0)
    try:
        new_idx = idefs.Add(name, "auto-generated block", base_pt, geom, attr)
        if new_idx is None:
            return -1
        return int(new_idx)
    except Exception:
        return -1


def _plane_on_curve(crv, t):
    # Use curve tangent for X axis and World Z as up
    try:
        pt = crv.PointAt(t)
        tan = crv.TangentAt(t)
        xaxis = tan
        zaxis = geo.Vector3d(0, 0, 1)
        # handle degenerate
        if xaxis.IsZero:
            xaxis = geo.Vector3d(1, 0, 0)
        yaxis = geo.Vector3d.CrossProduct(zaxis, xaxis)
        if yaxis.IsZero:
            yaxis = geo.Vector3d(0, 1, 0)
        plane = geo.Plane(pt, xaxis, yaxis)
        return plane
    except Exception:
        return geo.Plane.WorldXY


def _place_instances(doc, def_name, size_tuple, rail_crv, gap, layer_fullpath):
    """Place block instances along rail curve at regular gap.

    Returns list of created object ids (System.Guid)
    """
    ids = []
    if rail_crv is None:
        return ids
    def_index = _ensure_block_def(doc, def_name, size_tuple)
    if not isinstance(def_index, int) or def_index < 0:
        return ids

    # ensure layer
    try:
        # ensure top-level parent "Pedestrian" exists implicitly via split
        parts = layer_fullpath.split("::")
        parent_id = None
        for i, part in enumerate(parts):
            lyr = (
                ensure_layer(doc, part, parent_id=parent_id)
                if i > 0
                else ensure_layer(doc, part)
            )
            parent_id = lyr.Id if lyr else parent_id
        target_layer = find_layer_by_fullpath(doc, layer_fullpath)
    except Exception:
        target_layer = None

    attr = Rhino.DocObjects.ObjectAttributes()
    if target_layer:
        attr.LayerIndex = target_layer.Index

    # place points along curve
    length = rail_crv.GetLength()
    if length <= 0 or gap <= 0:
        return ids
    n = int(math.floor(length / gap)) + 1
    for i in range(n):
        s = min(i * gap, length)
        ok, t = rail_crv.LengthParameter(s)
        if not ok:
            t = rail_crv.Domain.ParameterAt(min(1.0, max(0.0, s / length)))
        plane = _plane_on_curve(rail_crv, t)
        xform = Rhino.Geometry.Transform.PlaneToPlane(geo.Plane.WorldXY, plane)
        try:
            obj_id = doc.Objects.AddInstanceObject(def_index, xform)
            if obj_id and target_layer:
                try:
                    obj = doc.Objects.FindId(obj_id)
                    if obj:
                        obj.Attributes.LayerIndex = target_layer.Index
                        doc.Objects.ModifyAttributes(obj, obj.Attributes, True)
                except Exception:
                    pass
            if obj_id:
                ids.append(obj_id)
        except Exception:
            pass
    return ids


if not RUN:
    raise Exception("Run이 False입니다. 실행하려면 True로 설정하세요.")

# Output containers for GH preview
walkways = []  # List[Brep]
tree_ids = []  # List[Guid]
light_ids = []
furniture_ids = []


for blk in BLOCKS:
    try:
        region_brep = blk
        if not isinstance(region_brep, geo.Brep):
            continue
        outer = _outer_boundary_from_region(region_brep)
        if not outer:
            continue
        inner = _offset_inward(outer, CONST.PEDESTRIAN_DEPTH)
        if inner:
            ring = _create_planar_ring(outer, inner)
            if ring:
                walkways.append(ring)

        # Rails for placements (use offsets from outer boundary inward)
        # Fallback: if offset fails, use inner curve if available, else outer
        def _rail(outer_crv, dist, inner_crv=None):
            r = _offset_inward(outer_crv, dist)
            if r is None and inner_crv is not None:
                r = inner_crv
            if r is None:
                r = outer_crv
            return r

        tree_rail = _rail(outer, CONST.TREE_OFFSET, inner)
        light_rail = _rail(outer, CONST.LIGHT_OFFSET, inner)
        furn_rail = _rail(outer, CONST.FURNITURE_OFFSET, inner)

        if BAKE:
            # Bake this block's walkway ring
            if "ring" in locals() and ring:
                lyr = ensure_layer(doc, CONST.LAYER_PEDESTRIAN_WALKWAY)
                attrs = Rhino.DocObjects.ObjectAttributes()
                if lyr:
                    attrs.LayerIndex = lyr.Index
                try:
                    doc.Objects.AddBrep(ring, attrs)
                except Exception:
                    pass

            # Trees / Lights / Furniture as block instances
            tree_ids.extend(
                _place_instances(
                    doc,
                    def_name="Tree_Block",
                    size_tuple=CONST.TREE_BOX_SIZE,
                    rail_crv=tree_rail,
                    gap=CONST.TREE_GAP,
                    layer_fullpath=CONST.LAYER_PEDESTRIAN_TREES,
                )
            )
            light_ids.extend(
                _place_instances(
                    doc,
                    def_name="Light_Block",
                    size_tuple=CONST.LIGHT_BOX_SIZE,
                    rail_crv=light_rail,
                    gap=CONST.LIGHT_GAP,
                    layer_fullpath=CONST.LAYER_PEDESTRIAN_LIGHTS,
                )
            )
            furniture_ids.extend(
                _place_instances(
                    doc,
                    def_name="Furniture_Block",
                    size_tuple=CONST.FURNITURE_BOX_SIZE,
                    rail_crv=furn_rail,
                    gap=CONST.FURNITURE_GAP,
                    layer_fullpath=CONST.LAYER_PEDESTRIAN_FURNITURE,
                )
            )
    except Exception as e:
        _dprint("Block failed:", blk, e)

try:
    if BAKE:
        doc.Views.Redraw()
except Exception:
    pass
