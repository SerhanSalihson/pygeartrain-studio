"""Involute gears: the single implementation shared by Gear Studio and actgen.

    from gearstudio.involute import design_gearset, check_strength, sweep, external_outline

geometry   tooth geometry, profile shift, backlash thinning, tip topping, exact outlines
planetary  planetary set design (zero-sum shift, phasing, contact ratio, clearances), enumeration
strength   Lewis bending with the form factor measured on the generated tooth
mesh       overlap / backlash sweep over many poses (shapely)
"""
from gearstudio.involute.geometry import (ext_space, external_outline, gear_polygon_external,  # noqa: F401
                                          gear_polygon_internal, half_angle, int_space, internal_outline, inv,
                                          ring_space, thickness, tooth_chord, top_tip_for_land, undercut_shift)
from gearstudio.involute.mesh import members, sweep  # noqa: F401
from gearstudio.involute.planetary import (GearRules, GearSet, design_gearset, enumerate_sets,  # noqa: F401
                                           explain_infeasible, min_shift, outlines,
                                           planet_phases)
from gearstudio.involute.strength import StrengthReport, check_strength, lewis_Y  # noqa: F401
