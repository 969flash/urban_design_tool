import Rhino
import Rhino.Geometry as rg
import ghpythonlib.components as ghcomp
import System


class Block:
    def __init__(self, region, landuse_name, block_id):
        self.region = region
        self.landuse_name = landuse_name
        self.block_id = block_id
        self.buildings = []  # trimmed building footprints per block


DEBUG = False
LANDUSE_PARENT = "Landuse"
TARGET_PARENT_LAYER = "Landuse-Road"
Z_EXTRUDE = 1.0
Z_LIMIT = 0.1


def dprint(*args):
    if DEBUG:
        try:
            print(*args)
        except Exception:
            pass


def extrude_srf(srf, height):
    """Surface/Brep를 z축으로 height만큼 Extrude한 Brep 반환."""
    extrusion = ghcomp.Extrude(srf, rg.Vector3d(0, 0, height))
    return ghcomp.CapHoles(extrusion)


def get_layer_surfaces(doc, parent_name):
    """parent_name 하위 레이어에서 Surface/Brep를 모두 Brep로 수집."""
    layer_dict = {}
    for layer in doc.Layers:
        if not layer.IsVisible:
            continue
        full_path = getattr(layer, "FullPath", layer.Name)
        parts = full_path.split("::") if full_path else []
        if len(parts) >= 2 and parts[0] == parent_name:
            child_name = parts[1]
            objs = [
                obj
                for obj in doc.Objects.FindByLayer(layer)
                if isinstance(obj.Geometry, (rg.Surface, rg.Brep))
            ]
            srfs = []
            for obj in objs:
                geo = obj.Geometry
                if isinstance(geo, rg.Surface):
                    srfs.append(rg.Brep.CreateFromSurface(geo))
                elif isinstance(geo, rg.Brep):
                    srfs.append(geo)
            if child_name in layer_dict:
                layer_dict[child_name].extend(srfs)
            else:
                layer_dict[child_name] = srfs
    return layer_dict


def is_point_on_srf(pt, srf):
    if pt is None:
        return False
    pt_on_srf = ghcomp.SurfaceClosestPoint(pt, srf).point
    return pt_on_srf.DistanceTo(pt) < 0.01


def get_point_inside_face(surface):
    meshes = rg.Mesh.CreateFromBrep(surface, rg.MeshingParameters.Default)
    if not meshes:
        return None
    mesh = meshes[0]
    if mesh.Faces.Count == 0:
        return None
    indices = mesh.Faces[0]
    p0 = mesh.Vertices[indices.A]
    p1 = mesh.Vertices[indices.B]
    p2 = mesh.Vertices[indices.C]
    return rg.Point3d(
        (p0.X + p1.X + p2.X) / 3.0,
        (p0.Y + p1.Y + p2.Y) / 3.0,
        (p0.Z + p1.Z + p2.Z) / 3.0,
    )


def collect_landuse_road_faces(
    doc,
    road_regions,
    landuse_parent=LANDUSE_PARENT,
    z_height=Z_EXTRUDE,
    z_limit=Z_LIMIT,
):
    """Landuse 면에서 도로를 차감한 후 유효 BrepFace 목록을 용도별로 반환."""
    landuse_dict = get_layer_surfaces(doc, landuse_parent)
    faces_by_landuse = {}

    road_breps = []
    for region in road_regions:
        road_brep = extrude_srf(region, z_height)
        if road_brep:
            road_breps.append(road_brep)

    for lu_name, lu_srfs in landuse_dict.items():
        collected_faces = []
        for lu_srf in lu_srfs:
            base_brep = extrude_srf(lu_srf, z_height)
            if not base_brep:
                continue
            diff_brep = base_brep
            for road_brep in road_breps:
                diff_brep = ghcomp.SolidDifference(diff_brep, road_brep)
                if not diff_brep:
                    break
            if not diff_brep:
                continue
            decon = ghcomp.DeconstructBrep(diff_brep)
            faces = decon[0]
            for face in faces:
                mp = rg.AreaMassProperties.Compute(face)
                if mp and mp.Centroid.Z > z_limit:
                    continue
                test_pt = get_point_inside_face(face)
                if not is_point_on_srf(test_pt, lu_srf):
                    continue
                collected_faces.append(face)
        if collected_faces:
            faces_by_landuse[lu_name] = collected_faces
    return faces_by_landuse


def _find_layer_by_fullpath(doc, fullpath):
    for ly in doc.Layers:
        fp = getattr(ly, "FullPath", None) or ly.Name or ""
        if fp == fullpath:
            return ly
    return None


def _ensure_layer(doc, name, parent_id=None):
    if parent_id:
        parent = doc.Layers.FindId(parent_id)
        parent_path = getattr(parent, "FullPath", parent.Name) if parent else None
        target_path = (parent_path + "::" + name) if parent_path else name
        found = _find_layer_by_fullpath(doc, target_path)
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


def _clear_layer_tree(doc, parent_name):
    parent = None
    for ly in doc.Layers:
        if ly.Name == parent_name and ly.ParentLayerId == System.Guid.Empty:
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


def _planar_breps_from_face(doc, face):
    breps = []
    try:
        fb = face.DuplicateFace(True)
        if fb and fb.IsValid:
            breps.append(fb)
    except Exception:
        fb = None
    if not breps:
        try:
            tol = doc.ModelAbsoluteTolerance if doc else 0.01
            crvs = []
            for loop in face.Loops:
                crv = loop.To3dCurve()
                if crv and crv.IsClosed:
                    crvs.append(crv)
            if crvs:
                made = rg.Brep.CreatePlanarBreps(crvs, tol)
                if made:
                    breps.extend([b for b in made if b and b.IsValid])
        except Exception:
            pass
    return breps


def planar_breps_by_landuse(doc, faces_by_landuse, z_limit=Z_LIMIT):
    planar = {}
    if not faces_by_landuse:
        return planar
    for lu_name, faces in faces_by_landuse.items():
        breps = []
        for face in faces:
            mp = rg.AreaMassProperties.Compute(face)
            if mp and mp.Centroid.Z > z_limit:
                continue
            breps.extend(_planar_breps_from_face(doc, face))
        if breps:
            planar[lu_name] = breps
    return planar


def bake_road_subregion_results(
    doc,
    planar_breps_by_lu,
    landuse_parent=LANDUSE_PARENT,
    target_parent=TARGET_PARENT_LAYER,
    clear_existing=True,
):
    if not planar_breps_by_lu:
        return 0
    parent_layer = _ensure_layer(doc, target_parent, parent_id=None)
    if not parent_layer:
        raise Exception("레이어 생성 실패: {}".format(target_parent))
    if clear_existing:
        _clear_layer_tree(doc, target_parent)
    baked = 0
    for lu_name, breps in planar_breps_by_lu.items():
        child_layer = _ensure_layer(doc, lu_name, parent_id=parent_layer.Id)
        if not child_layer:
            continue
        try:
            original = _find_layer_by_fullpath(doc, f"{landuse_parent}::{lu_name}")
            if original:
                lyr = doc.Layers[child_layer.Index]
                lyr.Color = original.Color
                doc.Layers.Modify(lyr, child_layer.Index, True)
        except Exception:
            pass
        attrs = Rhino.DocObjects.ObjectAttributes()
        attrs.LayerIndex = child_layer.Index
        for brep in breps:
            try:
                if isinstance(brep, rg.Brep):
                    obj_id = doc.Objects.AddBrep(brep, attrs)
                elif isinstance(brep, rg.Surface):
                    obj_id = doc.Objects.AddSurface(brep, attrs)
                else:
                    brep_try = rg.Brep.TryConvertBrep(brep)
                    obj_id = (
                        doc.Objects.AddBrep(brep_try, attrs)
                        if brep_try
                        else System.Guid.Empty
                    )
                if obj_id and obj_id != System.Guid.Empty:
                    baked += 1
            except Exception:
                pass
    try:
        doc.Views.Redraw()
    except Exception:
        pass
    return baked


def build_blocks(planar_breps_by_lu):
    blocks = []
    for lu_name, breps in planar_breps_by_lu.items():
        for idx, brep in enumerate(breps, start=1):
            try:
                block_id = f"{lu_name}_{idx}"
                blocks.append(
                    Block(region=brep, landuse_name=lu_name, block_id=block_id)
                )
            except Exception:
                pass
    return blocks


doc = Rhino.RhinoDoc.ActiveDoc
road_regions = globals().get("road_regions", [])
if not isinstance(road_regions, list):
    road_regions = [road_regions]
run = bool(globals().get("run", False))

if not run:
    raise Exception("run 입력이 False입니다. 실행을 원하면 True로 설정하세요.")

faces_cache = collect_landuse_road_faces(
    doc,
    road_regions,
    landuse_parent=LANDUSE_PARENT,
    z_height=Z_EXTRUDE,
    z_limit=Z_LIMIT,
)

planar_cache = planar_breps_by_landuse(doc, faces_cache, z_limit=Z_LIMIT)

try:
    baked_cnt = bake_road_subregion_results(
        doc,
        planar_cache,
        landuse_parent=LANDUSE_PARENT,
        target_parent=TARGET_PARENT_LAYER,
        clear_existing=True,
    )
    dprint(
        "BakeRoadSubRegion: baked {} objects under '{}'.".format(
            baked_cnt, TARGET_PARENT_LAYER
        )
    )
except Exception as bake_err:
    dprint("BakeRoadSubRegion 오류:", bake_err)

blocks = build_blocks(planar_cache)

a = None  # legacy GH output placeholder (area data removed)
b = None  # legacy GH output placeholder (file path removed)
report = "Area report 기능이 비활성화되었습니다."
out_lines = [
    "Landuse trimming complete.",
    "Landuse categories: {}".format(len(planar_cache)),
    "Blocks generated: {}".format(len(blocks)),
]
out = "\n".join(out_lines)
