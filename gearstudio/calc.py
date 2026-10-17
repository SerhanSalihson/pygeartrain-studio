"""Speed and torque through a gear train (rigid, constant efficiency)."""
import math
from dataclasses import dataclass, field


@dataclass
class MemberRow:
    label: str
    dof: str
    role: str
    rpm: float


@dataclass
class MeshRow:
    name: str
    pitch_d: float          # mm
    speed: float            # pitch-line velocity, m/s
    frequency: float        # tooth meshing frequency, Hz
    force: float = None     # tangential force per tooth contact, N (when the torque is known)


@dataclass
class CalcResult:
    members: list
    ratio: float
    output_rpm: float
    output_torque: float     # torque the output shaft delivers to the load, N·m (signed like its rotation)
    reaction: float          # torque needed to hold the fixed member / housing, N·m
    reaction_label: str
    power_in: float          # W
    power_out: float
    meshes: list = field(default_factory=list)


def calculate(scene, rpm_in, torque_in, efficiency=1.0, module=None):
    """All members' speeds, output torque, reaction torque and (with a module) mesh data.

    Signs follow the input: positive = same sense as the input's rotation."""
    ratio = scene.ratio_in
    seen, members = set(), []
    for m in scene.members:
        if m.dof in seen:
            continue
        seen.add(m.dof)
        label = scene.spec.dof_labels.get(m.dof, m.label)
        members.append(MemberRow(label, m.dof, scene.role(m.dof), rpm_in * scene.speed_per_input(m.dof)))
    for dof in scene.ratios:            # members without geometry (e.g. a hidden carrier)
        if dof not in seen:
            members.append(MemberRow(scene.spec.dof_labels.get(dof, dof), dof, scene.role(dof),
                                     rpm_in * scene.speed_per_input(dof)))

    output_rpm = rpm_in / ratio
    output_torque = efficiency * torque_in * ratio
    # external torques on the gearbox balance: input + (-output) + reaction = 0
    reaction = output_torque - torque_in
    fixed = [c for c in scene.cfg[2:] if c in scene.ratios]
    if len(scene.cfg) > 2 and len(fixed) == len(scene.cfg) - 2 == 1:
        reaction_label = f'{scene.spec.dof_labels.get(fixed[0], fixed[0])} (fixed)'
    else:
        reaction_label = 'Housing / frame'
    power_in = torque_in * rpm_in * 2 * math.pi / 60

    meshes = []
    sz = scene.spec.sizing
    if module and sz.kind == 'involute':
        v = scene.values
        by_name = {g.name: g for g in sz.gears(v)}
        factors = sz.stage_factors(v)
        rpm_of = {r.dof: r.rpm for r in members}
        torque_of = {scene.cfg[0]: torque_in, scene.cfg[1]: output_torque}
        if reaction_label != 'Housing / frame':
            torque_of[fixed[0]] = reaction
        n_paths = v.get('N', 1) if any(ms.carrier for ms in sz.meshes(v)) else 1
        for ms in sz.meshes(v):
            ga, gb = by_name[ms.a], by_name[ms.b]
            m = module * factors[ga.stage]
            d = m * ga.z
            rel = rpm_of.get(ga.dof, 0.0) - (rpm_of.get(ms.carrier, 0.0) if ms.carrier else 0.0)
            speed = abs(rel) * 2 * math.pi / 60 * d / 2 / 1000
            freq = ga.z * abs(rel) / 60
            # tangential force is known when one of the two gears carries a known torque;
            # with planets, the torque is shared between the N parallel paths
            force = None
            for g in (ga, gb):
                if g.dof in torque_of:
                    force = abs(torque_of[g.dof]) / (m * g.z / 2 / 1000) / max(1, n_paths)
                    break
            meshes.append(MeshRow(f'{ga.name} – {gb.name}', d, speed, freq, force))
    return CalcResult(members, ratio, output_rpm, output_torque, reaction, reaction_label,
                      power_in, power_in * efficiency, meshes)
