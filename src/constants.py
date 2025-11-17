# -*- coding: utf-8 -*-
"""Project-wide constants for RoadDetailBuilder.

All modules should import from here instead of hardcoding values.
"""

# ==============================================================================
# Layer names (FullPath style using :: separators)
# ==============================================================================
LAYER_SRC_CENTERLINE_PARENT: str = "Road::Centerline"

LAYER_BAKE_CENTERLINE: str = "Road::Lane::Centerline"
LAYER_BAKE_LANELINE: str = "Road::Lane::Laneline"
LAYER_BAKE_EDGELINE: str = "Road::Lane::EdgeLine"

# ==============================================================================
# Lane paint pattern (meters)
# ==============================================================================
LANE_PAINT_LENGTH: float = 5.0
LANE_GAP_LENGTH: float = 8.0

# ==============================================================================
# Geometry / numeric tolerances
# ==============================================================================
# Rhino model tolerance fallback used in utils and main
TOL: float = 1e-3

# Rounding precision for numeric outputs
ROUNDING_PRECISION: int = 6

# Big number used as miter limit etc.
BIGNUM: int = 10_000

# Additional operation tolerance (if needed by ops)
OP_TOL: float = 1e-3

# Clipper components tolerance (for polyline boolean/offset)
CLIPPER_TOL: float = 1e-3

# Angle tolerance in radians (about 1 degree)
import math as _math

ANGLE_TOL: float = _math.radians(1.0)

# ==============================================================================
# Pedestrian generation defaults
# ==============================================================================
# Walkway band depth (meters)
PEDESTRIAN_DEPTH: float = 3.0

# Street trees placement
TREE_OFFSET: float = 1.0
TREE_GAP: float = 10.0

# Street lights placement
LIGHT_OFFSET: float = 0.5
LIGHT_GAP: float = 5.0

# Street furniture placement
FURNITURE_OFFSET: float = 1.0
FURNITURE_GAP: float = 15.0

# Block geometry sizes (width, depth, height) in meters
TREE_BOX_SIZE = (0.5, 0.5, 5.0)
LIGHT_BOX_SIZE = (0.5, 0.5, 3.0)
FURNITURE_BOX_SIZE = (0.5, 0.5, 0.5)

# Layers for pedestrian outputs
LAYER_PEDESTRIAN_WALKWAY: str = "Pedestrian::Walkway"
LAYER_PEDESTRIAN_TREES: str = "Pedestrian::Trees"
LAYER_PEDESTRIAN_LIGHTS: str = "Pedestrian::Lights"
LAYER_PEDESTRIAN_FURNITURE: str = "Pedestrian::Furniture"
