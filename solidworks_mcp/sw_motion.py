# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Native MotionManager studies: lifecycle, timeline, features, solver results and animation.

Every mutating call reads the native definition or result object back instead of
trusting the return code.  Whether a study type, a solver or an output format is
actually available comes from the live study, because it depends on which
SOLIDWORKS Motion components are installed and licensed.
"""

import math
import time
from pathlib import Path

import pythoncom
import win32com.client

from .sw_core import (
    active_document, as_list, byref_long, document_type, extension, flag_methods,
    iter_components, require_selection, result, safe, to_deg, tool, value,
)
from .sw_file import validated_output_path

TYPES = {"animation": 1, "basic_motion": 2, "motion_analysis": 4}
SIMULATION_TYPES = (2, 4)
MOTOR_TYPES = {"linear": 77, "rotational": 78}
# swFeatureNameID_e: 75 linear force, 76 torque, 79-82 springs, 83-84 dampers, 85 3D contact.
FORCE_TYPES = {"linear": 75, "torque": 76}
SPRING_TYPES = {"linear": 79, "torsional": 80, "linear_motion": 81, "torsional_motion": 82}
DAMPER_TYPES = {"linear": 83, "torsional": 84}
CONTACT_TYPE = 85
# swSimulationForceFunctionType_e
FORCE_FUNCTIONS = {"constant": 0, "step": 1, "harmonic": 2, "function": 3, "spline": 4}
# swMotionContactFrictionType_e
FRICTION_OPTIONS = {"off": 0, "full": 1, "dynamic": 2}
# Creation reads these back from the study's own feature list: the motion springs are
# stored as the plain spring type of the same direction, which is why 81/82 map to
# the linear/torsional feature type instead of a separate coil-spring feature.
FORCE_FEATURE_TYPES = {"linear": "AEMLinearForce", "torque": "AEMTorque"}
SPRING_FEATURE_TYPES = {"linear": "AEMLinearSpring", "torsional": "AEMTorsionalSpring",
                        "linear_motion": "AEMLinearSpring", "torsional_motion": "AEMTorsionalSpring"}
DAMPER_FEATURE_TYPES = {"linear": "AEMLinearDamper", "torsional": "AEMTorsionalDamper"}
GRAVITY_AXES = {"x": 0, "y": 1, "z": 2}
PART_DOCUMENT = 1
ASSEMBLY_DOCUMENT = 2
PLAY_MODES = {"normal": 1, "loop": 2, "reciprocate": 3}
RENDERERS = {"screen": 0, "photoworks": 1}
# swAnimationOutputType_e
FRAME_FORMATS = {"avi": 1, "bmp": 2, "tga": 3, "png": 4, "jpg": 5, "tif": 6,
                 "mp4": 7, "mkv": 8, "flv": 9, "lxo": 10}
NAME = {"type": "string", "minLength": 1}
TYPE = {"type": "string", "enum": list(TYPES), "default": "animation"}
TWO_REFERENCES = {"type": "array", "minItems": 2, "maxItems": 2,
                   "items": {"type": "object", "description": "Selection specification for one end point."}}

# Members called with arguments.  Properties are deliberately absent: flagging a
# property as a method makes its put unresolvable.
_STUDY_METHODS = (
    "CreateDefinition", "CreateFeature", "Calculate", "GetResults", "GetProperties",
    "GetMotionFeatures", "GetMotionFeaturesCount", "GetNumOfExternalMotors",
    "GetNumOfExternalForces", "Activate", "SetDuration", "SetTime", "SaveToAVI",
    "CreateByRotateModel", "CreateByExplode", "CreateByCollapse",
)
_RESULT_METHODS = (
    "GetCMPosition", "GetLinearVelocity", "GetLinearAcceleration",
    "GetAngularVelocity", "GetAngularAcceleration", "GetEulerAngles",
)


def _name(raw):
    name = str(raw).strip()
    if not name:
        raise RuntimeError("Motion study name must not be empty.")
    return name


class MotionElementsUnsupported(RuntimeError):
    """The active document type cannot host native motion elements.

    A part document owns a MotionManager, but only for model animation.  Asking
    it for a gravity or motor feature fails inside ``CreateFeature`` with a raw
    COM server fault instead of a diagnosable return value, so the tool checks
    the document type first and reports the limitation itself.
    """

    def __init__(self, label: str):
        super().__init__(f"Native motion elements (gravity and motors) require an assembly document; "
                         f"the active document is a {label}.")
        self.label = label


def _manager(require_elements: bool = False):
    _, doc = active_document()
    kind = document_type(doc)
    if kind not in (PART_DOCUMENT, ASSEMBLY_DOCUMENT):
        raise RuntimeError("Motion studies require an active part or assembly.")
    if require_elements and kind != ASSEMBLY_DOCUMENT:
        raise MotionElementsUnsupported({PART_DOCUMENT: "part"}.get(kind, f"document type {kind}"))
    manager = value(extension(doc), "GetMotionStudyManager")
    if manager is None:
        raise RuntimeError("The native MotionManager is unavailable for this document.")
    return flag_methods(manager, "GetMotionStudy", "ActivateMotionStudy", "DeleteMotionStudy",
                        "CreateAVIParameter")


def _names(manager):
    return [str(name) for name in as_list(value(manager, "GetMotionStudyNames"))]


def _study(manager, name):
    if name not in _names(manager):
        raise RuntimeError(f"No motion study named '{name}'. Use list_motion_studies first.")
    study = manager.GetMotionStudy(name)
    if study is None:
        raise RuntimeError(f"MotionManager could not access '{name}'.")
    return flag_methods(study, *_STUDY_METHODS)


def _supported(study):
    mask = byref_long()
    if not study.GetSupportedStudyTypes(mask):
        raise RuntimeError("MotionManager could not read the supported study types.")
    return int(mask.value)


def _info(study):
    mask = _supported(study)
    kind = int(value(study, "StudyType"))
    return {"name": str(value(study, "Name")), "type": next((name for name, code in TYPES.items() if code == kind), str(kind)),
            "type_code": kind, "active": bool(value(study, "IsActive")),
            "duration_sec": float(value(study, "GetDuration")), "time_sec": float(value(study, "GetTime")),
            "supported_types": [name for name, code in TYPES.items() if mask & code], "supported_type_mask": mask}


def _type(raw):
    if raw not in TYPES:
        raise RuntimeError(f"Unknown motion study type '{raw}'.")
    return TYPES[raw]


def _activate(manager, study):
    if bool(value(study, "IsActive")):
        return True
    return bool(manager.ActivateMotionStudy(str(value(study, "Name")))) and bool(value(study, "IsActive"))


def _features(study):
    return [{"name": str(safe(feature, "Name", "")), "type": str(safe(feature, "GetTypeName2", ""))}
            for feature in as_list(value(study, "GetMotionFeatures"))]


def _results(study, code):
    try:
        return study.GetResults(code)
    except Exception:
        return None


# Native result vectors and angles are SI: metres, metres/second and radians.
def _triple(raw, scale=1.0):
    if raw is None:
        return None
    try:
        raw = value(raw, "ArrayData")
    except Exception:
        pass
    try:
        return [round(float(item) * scale, 9) for item in list(raw)[:3]]
    except Exception:
        return None


def _component(doc, name=None):
    components = iter_components(doc, True)
    if name:
        for component in components:
            if str(safe(component, "Name2", "")) == name:
                return component
        raise RuntimeError(f"No top-level component named '{name}'.")
    return components[0] if components else None


def _two_references(doc, references):
    """Select both end points of a motion element in a single selection set."""
    if not isinstance(references, (list, tuple)) or len(references) != 2:
        raise RuntimeError("Provide exactly two reference selections for the two end points.")
    objects = []
    for index, spec in enumerate(references, start=1):
        count = require_selection(doc, spec, mark=index, append=index > 1)
        if count != 1:
            raise RuntimeError(f"End point {index} must select exactly one object, not {count}.")
        selection = flag_methods(doc.SelectionManager, "GetSelectedObject6")
        reference = selection.GetSelectedObject6(index, -1)
        if reference is None:
            raise RuntimeError(f"End point {index} resolved to nothing after selection.")
        objects.append(reference)
    return objects


def _create_feature(study, definition):
    """Create a motion feature and identify it by the study's own feature list.

    The dispatch object CreateFeature returns can still report the previous
    feature's name and type on this build, so the new entry is found by diffing
    GetMotionFeatures instead of trusting the returned object.
    """
    before = [entry["name"] for entry in _features(study)]
    feature = study.CreateFeature(definition)
    if feature is None:
        return None, None
    for entry in reversed(_features(study)):
        if entry["name"] not in before:
            return feature, entry
    return feature, {"name": str(safe(feature, "Name", "")), "type": str(safe(feature, "GetTypeName2", ""))}


def _dispatch_array(objects):
    """A SAFEARRAY of dispatch pointers; the contact data object requires one."""
    return win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH,
                                   tuple(entry._oleobj_ for entry in objects))


def _sample(results, component, times):
    flag_methods(results, *_RESULT_METHODS)
    samples = []
    for moment in times:
        entry = {"time_sec": moment}
        for key, member, scale in (("position_mm", "GetCMPosition", 1000.0),
                                   ("linear_velocity_mm_per_s", "GetLinearVelocity", 1000.0),
                                   ("linear_acceleration_mm_per_s2", "GetLinearAcceleration", 1000.0),
                                   ("angular_velocity_rad_per_s", "GetAngularVelocity", 1.0),
                                   ("angular_acceleration_rad_per_s2", "GetAngularAcceleration", 1.0),
                                   ("euler_angles_deg", "GetEulerAngles", to_deg(1.0))):
            try:
                entry[key] = _triple(getattr(results, member)(moment, component), scale)
            except Exception:
                entry[key] = None
        samples.append(entry)
    return samples


def _differs(left, right, tolerance=1e-9):
    if left is None or right is None:
        return False
    return any(abs(float(x) - float(y)) > tolerance for x, y in zip(left, right))


def _moved(samples):
    """True once any sampled quantity changes; a static study stays False."""
    if len(samples) < 2:
        return False
    first = samples[0]
    for entry in samples[1:]:
        for key in ("position_mm", "linear_velocity_mm_per_s", "angular_velocity_rad_per_s"):
            if _differs(entry.get(key), first.get(key)):
                return True
    return False


def _sample_times(study, requested):
    if requested:
        times = sorted({float(moment) for moment in requested})
    else:
        duration = float(value(study, "GetDuration"))
        times = [0.0] if duration <= 0 else sorted({0.0, round(duration / 2.0, 6), round(duration, 6)})
    if any(not math.isfinite(moment) or moment < 0 for moment in times):
        raise RuntimeError("Sample times must be finite and non-negative.")
    duration = float(value(study, "GetDuration"))
    if times and duration > 0 and times[-1] > duration + 1e-9:
        raise RuntimeError(f"Sample time {times[-1]} is beyond the study duration {duration}.")
    return times


def _await_files(target: Path, deadline_sec: float = 30.0):
    """Wait for the animator to finish writing; frames land while the call returns."""
    series = target.suffix.lower() != ".avi"
    deadline = time.monotonic() + deadline_sec
    previous = None
    stable = 0
    while True:
        current = sorted(target.parent.glob(f"{target.stem}-*{target.suffix}")) if series else (
            [target] if target.is_file() else [])
        signature = [(str(path), path.stat().st_size) for path in current]
        ready = [path for path in current if path.stat().st_size > 0]
        if ready and signature == previous:
            stable += 1
            if stable >= 2:
                return ready
        else:
            stable = 0
        previous = signature
        if time.monotonic() >= deadline:
            return ready
        time.sleep(0.5)


def _set_type(study, code):
    if not _supported(study) & code:
        return result(False, "Requested study type is unavailable in the current installed/loaded/licensed session.", study=_info(study))
    study.StudyType = code
    info = _info(study)
    return result(info["type_code"] == code, "Read back motion study type.", study=info)


@tool("list_motion_studies", "Read-only: list native MotionManager studies, timeline times and actually supported types.")
def list_motion_studies(args):
    manager = _manager()
    names = _names(manager)
    studies = [_info(_study(manager, name)) for name in names]
    count = int(value(manager, "GetMotionStudyCount"))
    return result(count == len(studies), "Read motion studies.", studies=studies, count=count)


@tool("create_motion_study", "Create and name a native motion study. Defaults to animation; unsupported simulation types are reported as unavailable.",
      {"name": NAME, "type": TYPE}, ["name"])
def create_motion_study(args):
    name = _name(args["name"])
    code = _type(args.get("type", "animation"))
    manager = _manager()
    if name in _names(manager):
        raise RuntimeError(f"Motion study '{name}' already exists.")
    study = value(manager, "CreateMotionStudy")
    if study is None:
        return result(False, "Native motion study creation failed.")
    study = flag_methods(study, *_STUDY_METHODS)
    study.Name = name
    output = _set_type(study, code)
    if str(value(study, "Name")) != name or name not in _names(manager):
        return result(False, "Created study, but the requested name was not applied.", study=_info(study))
    return output


@tool("activate_motion_study", "Activate an existing native motion study and read back its active state.", {"name": NAME}, ["name"])
def activate_motion_study(args):
    manager = _manager()
    name = _name(args["name"])
    study = _study(manager, name)
    accepted = bool(manager.ActivateMotionStudy(name))
    info = _info(study)
    return result(accepted and info["active"], "Read back motion study activation.", study=info)


@tool("delete_motion_study", "Delete the named motion study and its animation/simulation data; verify it disappears from MotionManager.", {"name": NAME}, ["name"])
def delete_motion_study(args):
    manager = _manager()
    name = _name(args["name"])
    _study(manager, name)
    accepted = bool(manager.DeleteMotionStudy(name))
    names = _names(manager)
    return result(accepted and name not in names, "Read back motion study deletion.", remaining_names=names)


@tool("duplicate_motion_study", "Duplicate an existing motion study, assign a new unique name, and read back timeline/type state.",
      {"name": NAME, "new_name": NAME}, ["name", "new_name"])
def duplicate_motion_study(args):
    manager = _manager()
    name, new_name = _name(args["name"]), _name(args["new_name"])
    if new_name in _names(manager):
        raise RuntimeError(f"Motion study '{new_name}' already exists.")
    study = value(_study(manager, name), "Duplicate")
    if study is None:
        return result(False, "Native motion study duplication failed.")
    study = flag_methods(study, *_STUDY_METHODS)
    study.Name = new_name
    info = _info(study)
    return result(info["name"] == new_name and new_name in _names(manager), "Read back duplicated motion study.", study=info)


@tool("set_motion_study_type", "Set animation, Basic Motion or Motion Analysis only when native MotionManager reports that type is supported.",
      {"name": NAME, "type": TYPE}, ["name", "type"])
def set_motion_study_type(args):
    code = _type(args["type"])
    manager = _manager()
    return _set_type(_study(manager, _name(args["name"])), code)


@tool("set_motion_study_timing", "Set native timeline duration and/or cursor time in seconds, checking bounds before any mutation and reading values back.",
      {"name": NAME, "duration_sec": {"type": "number", "exclusiveMinimum": 0}, "time_sec": {"type": "number", "minimum": 0}}, ["name"])
def set_motion_study_timing(args):
    updates = {key: float(args[key]) for key in ("duration_sec", "time_sec") if key in args}
    if not updates or any(not math.isfinite(v) or v < 0 or (k == "duration_sec" and v == 0) for k, v in updates.items()):
        raise RuntimeError("Provide a finite positive duration and/or a finite nonnegative cursor time.")
    manager = _manager()
    study = _study(manager, _name(args["name"]))
    before = _info(study)
    duration = updates.get("duration_sec", before["duration_sec"])
    if updates.get("time_sec", 0) > duration:
        raise RuntimeError("Cursor time must not exceed the study duration.")
    if not _activate(manager, study):
        return result(False, "Could not activate the study before setting its timeline.", study=before)
    accepted = True
    if "duration_sec" in updates:
        accepted = bool(study.SetDuration(duration))
    if "time_sec" in updates:
        # The cursor move is applied even when the preceding SetDuration reports
        # false, which has been observed right after a study-type switch, so the
        # read-back decides and the native flag is reported separately.
        study.SetTime(updates["time_sec"])
    info = _info(study)
    matches = all(math.isclose(info[k], v, rel_tol=1e-7, abs_tol=1e-7) for k, v in updates.items())
    return result(matches, "Read back motion study timeline.", study=info, native_accepted=accepted)


@tool("list_motion_features", "Read-only: list a motion study's native motion features with their localised names and types, plus the external motor and force counters.",
      {"name": NAME}, ["name"])
def list_motion_features(args):
    manager = _manager()
    study = _study(manager, _name(args["name"]))
    count = int(value(study, "GetMotionFeaturesCount"))
    features = _features(study)
    return result(count == len(features), "Read motion features.", study=_info(study), count=count,
                  features=features, external_motors=int(value(study, "GetNumOfExternalMotors")),
                  external_forces=int(value(study, "GetNumOfExternalForces")))


@tool("add_motion_gravity", "Create a native gravity feature in a motion study, then read the stored definition back.",
      {"name": NAME, "strength": {"type": "number", "exclusiveMinimum": 0, "default": 9.80665},
       "axis": {"type": "string", "enum": list(GRAVITY_AXES), "default": "y"},
       "reverse_direction": {"type": "boolean", "default": False}}, ["name"])
def add_motion_gravity(args):
    strength = float(args.get("strength", 9.80665))
    if not math.isfinite(strength) or strength <= 0:
        raise RuntimeError("Gravity strength must be a finite positive number in m/s^2.")
    axis = GRAVITY_AXES[str(args.get("axis", "y")).lower()]
    reverse = bool(args.get("reverse_direction", False))
    try:
        manager = _manager(require_elements=True)
    except MotionElementsUnsupported as exc:
        return result(False, str(exc), document_type=exc.label)
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before adding gravity.", study=_info(study))
    definition = study.CreateDefinition(74)
    if definition is None:
        return result(False, "SOLIDWORKS returned no gravity feature data object.")
    definition.Strength = strength
    definition.ReverseDirection = reverse
    definition.Axis = axis
    feature, created = _create_feature(study, definition)
    if feature is None:
        return result(False, "SOLIDWORKS refused the gravity feature.")
    stored = {"strength": float(value(definition, "Strength")), "reverse_direction": bool(value(definition, "ReverseDirection")),
              "axis": int(value(definition, "Axis"))}
    features = _features(study)
    confirmed = (created["type"] == "AEMGravity"
                 and math.isclose(stored["strength"], strength, rel_tol=1e-9)
                 and stored["reverse_direction"] == reverse and stored["axis"] == axis)
    return result(confirmed, "Read the created gravity feature back.", feature=created, definition=stored,
                  features=features, count=int(value(study, "GetMotionFeaturesCount")))


@tool("add_motion_motor", "Create a native linear or rotational motor along selected geometry and read the stored constant speed back.",
      {"name": NAME, "motor_type": {"type": "string", "enum": list(MOTOR_TYPES), "default": "rotational"},
       "direction": {"type": "object", "description": "Selection of the edge, axis or face that defines the motor direction."},
       "speed": {"type": "number", "description": "Constant speed for the native constant-speed motor (RPM per IMotionMotorFeatureData::ConstantSpeedMotor)."},
       "reverse_direction": {"type": "boolean", "default": False}}, ["name", "direction", "speed"])
def add_motion_motor(args):
    motor_type = str(args.get("motor_type", "rotational"))
    if motor_type not in MOTOR_TYPES:
        raise RuntimeError(f"Unknown motor type '{motor_type}'.")
    speed = float(args["speed"])
    if not math.isfinite(speed):
        raise RuntimeError("Motor speed must be finite.")
    reverse = bool(args.get("reverse_direction", False))
    _, doc = active_document()
    try:
        manager = _manager(require_elements=True)
    except MotionElementsUnsupported as exc:
        return result(False, str(exc), document_type=exc.label)
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before adding the motor.", study=_info(study))
    require_selection(doc, args["direction"], mark=1)
    selection_manager = flag_methods(doc.SelectionManager, "GetSelectedObject6")
    reference = selection_manager.GetSelectedObject6(1, -1)
    if reference is None:
        return result(False, "The direction selection resolved to nothing.")
    definition = study.CreateDefinition(MOTOR_TYPES[motor_type])
    if definition is None:
        return result(False, "SOLIDWORKS returned no motor feature data object.")
    definition.DirectionReference = reference
    definition.ReverseDirection = reverse
    definition.ConstantSpeedMotor(speed)
    stored = {"speed": float(value(definition, "Velocity")), "reverse_direction": bool(value(definition, "ReverseDirection")),
              "motor_type": int(value(definition, "MotorType"))}
    feature, created = _create_feature(study, definition)
    if feature is None:
        return result(False, "SOLIDWORKS refused the motor feature.", definition=stored)
    features = _features(study)
    stored = {"speed": float(value(definition, "Velocity")), "reverse_direction": bool(value(definition, "ReverseDirection")),
              "motor_type": int(value(definition, "MotorType"))}
    confirmed = (created["type"] == ("AEMLinearMotor" if motor_type == "linear" else "AEMRotationalMotor")
                 and math.isclose(stored["speed"], speed, rel_tol=1e-9)
                 and stored["reverse_direction"] == reverse
                 and stored["motor_type"] == (0 if motor_type == "linear" else 1))
    return result(confirmed, "Read the created motor feature back.", feature=created, definition=stored,
                  features=features, count=int(value(study, "GetMotionFeaturesCount")))


@tool("add_motion_force", "Create a constant native linear force or torque between two selected references and read the stored function back.",
      {"name": NAME, "force_type": {"type": "string", "enum": list(FORCE_TYPES), "default": "linear"},
       "magnitude": {"type": "number", "description": "Constant value in the document force unit (N or N m for torque)."},
       "reverse_direction": {"type": "boolean", "default": False},
       "references": TWO_REFERENCES}, ["name", "magnitude", "references"])
def add_motion_force(args):
    magnitude = float(args["magnitude"])
    if not math.isfinite(magnitude) or magnitude == 0:
        raise RuntimeError("Force magnitude must be a finite non-zero number.")
    force_type = str(args.get("force_type", "linear"))
    if force_type not in FORCE_TYPES:
        raise RuntimeError(f"Unknown force type '{force_type}'.")
    reverse = bool(args.get("reverse_direction", False))
    try:
        manager = _manager(require_elements=True)
    except MotionElementsUnsupported as exc:
        return result(False, str(exc), document_type=exc.label)
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before adding the force.", study=_info(study))
    _, doc = active_document()
    references = _two_references(doc, args["references"])
    definition = flag_methods(study.CreateDefinition(FORCE_TYPES[force_type]), "SetEndPoints", "GetEndPoints")
    if definition is None:
        return result(False, "SOLIDWORKS returned no force feature data object.")
    definition.SetEndPoints(*references)
    definition.ForceFunctionType = FORCE_FUNCTIONS["constant"]
    definition.FunctionConstantValue = magnitude
    definition.ReverseDirection = reverse
    stored = {"magnitude": float(value(definition, "FunctionConstantValue")),
              "function_type": int(value(definition, "ForceFunctionType")),
              "force_type": int(value(definition, "ForceType")),
              "action_type": int(value(definition, "ActionType")),
              "reverse_direction": bool(value(definition, "ReverseDirection"))}
    feature, created = _create_feature(study, definition)
    if feature is None:
        return result(False, "SOLIDWORKS refused the force feature.", definition=stored)
    confirmed = (created["type"] == FORCE_FEATURE_TYPES[force_type]
                 and math.isclose(stored["magnitude"], magnitude, rel_tol=1e-9)
                 and stored["force_type"] == (0 if force_type == "linear" else 1)
                 and stored["reverse_direction"] == reverse)
    return result(confirmed, "Read the created force feature back.", feature=created, definition=stored,
                  features=_features(study), count=int(value(study, "GetMotionFeaturesCount")))


@tool("add_motion_spring", "Create a native linear, torsional or coil motion spring between two selected references and read the stored characteristics back.",
      {"name": NAME, "spring_type": {"type": "string", "enum": list(SPRING_TYPES), "default": "linear"},
       "spring_constant": {"type": "number", "exclusiveMinimum": 0},
       "free_length": {"type": "number", "exclusiveMinimum": 0, "description": "Linear springs only."},
       "coil_diameter": {"type": "number", "exclusiveMinimum": 0, "description": "Coil motion springs only."},
       "number_of_coils": {"type": "integer", "minimum": 1, "description": "Coil motion springs only."},
       "wire_diameter": {"type": "number", "exclusiveMinimum": 0, "description": "Coil motion springs only."},
       "references": TWO_REFERENCES}, ["name", "spring_constant", "references"])
def add_motion_spring(args):
    constant = float(args["spring_constant"])
    if not math.isfinite(constant) or constant <= 0:
        raise RuntimeError("Spring constant must be a finite positive number.")
    spring_type = str(args.get("spring_type", "linear"))
    if spring_type not in SPRING_TYPES:
        raise RuntimeError(f"Unknown spring type '{spring_type}'.")
    for key in ("free_length", "coil_diameter", "wire_diameter"):
        if key in args and (not math.isfinite(float(args[key])) or float(args[key]) <= 0):
            raise RuntimeError(f"{key} must be a finite positive number.")
    if "number_of_coils" in args and int(args["number_of_coils"]) < 1:
        raise RuntimeError("number_of_coils must be at least one.")
    coil_spring = spring_type in ("linear_motion", "torsional_motion")
    if "free_length" in args and coil_spring:
        raise RuntimeError("free_length applies to the linear and torsional spring types, not to the coil motion springs.")
    if not coil_spring and any(key in args for key in ("coil_diameter", "number_of_coils", "wire_diameter")):
        raise RuntimeError("Coil diameter, coil count and wire diameter apply only to the coil motion springs.")
    try:
        manager = _manager(require_elements=True)
    except MotionElementsUnsupported as exc:
        return result(False, str(exc), document_type=exc.label)
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before adding the spring.", study=_info(study))
    _, doc = active_document()
    references = _two_references(doc, args["references"])
    definition = flag_methods(study.CreateDefinition(SPRING_TYPES[spring_type]), "SetEndPoints", "GetEndPoints")
    if definition is None:
        return result(False, "SOLIDWORKS returned no spring feature data object.")
    definition.SetEndPoints(*references)
    definition.SpringConstant = constant
    requested = {"spring_constant": constant}
    stored = {"spring_constant": float(value(definition, "SpringConstant"))}
    if "free_length" in args:
        definition.FreeLength = float(args["free_length"])
        requested["free_length"] = float(args["free_length"])
        stored["free_length"] = float(value(definition, "FreeLength"))
    for key, attributename in (("coil_diameter", "CoilDiameter"), ("number_of_coils", "NumberOfCoils"),
                               ("wire_diameter", "WireDiameter")):
        if key not in args:
            continue
        setattr(definition, attributename, args[key])
        requested[key] = args[key]
        stored[key] = value(definition, attributename)
    feature, created = _create_feature(study, definition)
    if feature is None:
        return result(False, "SOLIDWORKS refused the spring feature.", definition=stored)
    confirmed = created["type"] == SPRING_FEATURE_TYPES[spring_type]
    for key, wanted in requested.items():
        actual = stored.get(key)
        if key == "number_of_coils":
            confirmed = confirmed and int(actual) == int(wanted)
        else:
            confirmed = confirmed and math.isclose(float(actual), float(wanted), rel_tol=1e-9)
    return result(confirmed, "Read the created spring feature back.", feature=created, definition=stored,
                  requested=requested, features=_features(study), count=int(value(study, "GetMotionFeaturesCount")))


@tool("add_motion_damper", "Create a native linear or torsional damper between two selected references and read the stored damping constant back.",
      {"name": NAME, "damper_type": {"type": "string", "enum": list(DAMPER_TYPES), "default": "linear"},
       "damping_constant": {"type": "number", "exclusiveMinimum": 0},
       "references": TWO_REFERENCES}, ["name", "damping_constant", "references"])
def add_motion_damper(args):
    constant = float(args["damping_constant"])
    if not math.isfinite(constant) or constant <= 0:
        raise RuntimeError("Damping constant must be a finite positive number.")
    damper_type = str(args.get("damper_type", "linear"))
    if damper_type not in DAMPER_TYPES:
        raise RuntimeError(f"Unknown damper type '{damper_type}'.")
    try:
        manager = _manager(require_elements=True)
    except MotionElementsUnsupported as exc:
        return result(False, str(exc), document_type=exc.label)
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before adding the damper.", study=_info(study))
    _, doc = active_document()
    references = _two_references(doc, args["references"])
    definition = flag_methods(study.CreateDefinition(DAMPER_TYPES[damper_type]), "SetEndPoints", "GetEndPoints")
    if definition is None:
        return result(False, "SOLIDWORKS returned no damper feature data object.")
    definition.SetEndPoints(*references)
    definition.DampingConstant = constant
    stored = {"damping_constant": float(value(definition, "DampingConstant")),
              "type": int(value(definition, "Type"))}
    feature, created = _create_feature(study, definition)
    if feature is None:
        return result(False, "SOLIDWORKS refused the damper feature.", definition=stored)
    confirmed = (created["type"] == DAMPER_FEATURE_TYPES[damper_type]
                 and math.isclose(stored["damping_constant"], constant, rel_tol=1e-9))
    return result(confirmed, "Read the created damper feature back.", feature=created, definition=stored,
                  features=_features(study), count=int(value(study, "GetMotionFeaturesCount")))


@tool("add_motion_contact", "Create a native 3D contact feature between two components and read the contact parameters back.",
      {"name": NAME,
       "components": {"type": "array", "minItems": 2, "maxItems": 2,
                      "items": {"type": "string", "minLength": 1},
                      "description": "Two distinct top-level component names."},
       "stiffness": {"type": "number", "exclusiveMinimum": 0},
       "exponent": {"type": "number", "exclusiveMinimum": 0},
       "max_damping": {"type": "number", "minimum": 0},
       "penetration": {"type": "number", "exclusiveMinimum": 0},
       "friction_option": {"type": "string", "enum": list(FRICTION_OPTIONS), "default": "full"},
       "use_restitution": {"type": "boolean", "default": False},
       "restitution": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.5}},
      ["name", "components"])
def add_motion_contact(args):
    names = [str(entry) for entry in args["components"]]
    if len(names) != 2 or len(set(names)) != 2:
        raise RuntimeError("Provide two distinct component names for the contact pair.")
    friction = str(args.get("friction_option", "full"))
    if friction not in FRICTION_OPTIONS:
        raise RuntimeError(f"Unknown friction option '{friction}'.")
    for key in ("stiffness", "exponent", "penetration"):
        if key in args and (not math.isfinite(float(args[key])) or float(args[key]) <= 0):
            raise RuntimeError(f"{key} must be a finite positive number.")
    if "max_damping" in args and (not math.isfinite(float(args["max_damping"])) or float(args["max_damping"]) < 0):
        raise RuntimeError("max_damping must be a finite non-negative number.")
    restitution = float(args.get("restitution", 0.5))
    if not math.isfinite(restitution) or not 0 <= restitution <= 1:
        raise RuntimeError("restitution must be between 0 and 1.")
    use_restitution = bool(args.get("use_restitution", False))
    try:
        manager = _manager(require_elements=True)
    except MotionElementsUnsupported as exc:
        return result(False, str(exc), document_type=exc.label)
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before adding the contact.", study=_info(study))
    _, doc = active_document()
    try:
        components = [_component(doc, name) for name in names]
    except RuntimeError as exc:
        return result(False, str(exc), components=names)
    definition = study.CreateDefinition(CONTACT_TYPE)
    if definition is None:
        return result(False, "SOLIDWORKS returned no 3D contact feature data object.")
    definition.ContactComponents = _dispatch_array(components)
    definition.FrictionOption = FRICTION_OPTIONS[friction]
    definition.UseRestitutionCoefficient = use_restitution
    definition.RestitutionCoefficient = restitution
    requested = {"friction_option": FRICTION_OPTIONS[friction], "use_restitution": use_restitution,
                 "restitution": restitution}
    for key, attributename in (("stiffness", "Stiffness"), ("exponent", "Exponent"),
                               ("max_damping", "MaxDamping"), ("penetration", "Penetration")):
        if key in args:
            setattr(definition, attributename, float(args[key]))
            requested[key] = float(args[key])
    stored = {"stiffness": float(value(definition, "Stiffness")), "exponent": float(value(definition, "Exponent")),
              "max_damping": float(value(definition, "MaxDamping")),
              "penetration": float(value(definition, "Penetration")),
              "friction_option": int(value(definition, "FrictionOption")),
              "use_restitution": bool(value(definition, "UseRestitutionCoefficient")),
              "restitution": float(value(definition, "RestitutionCoefficient"))}
    feature, created = _create_feature(study, definition)
    if feature is None:
        return result(False, "SOLIDWORKS refused the 3D contact feature.", definition=stored, components=names)
    confirmed = created["type"] == "AEM3DContact"
    for key, wanted in requested.items():
        actual = stored[key]
        if key in ("friction_option", "use_restitution"):
            confirmed = confirmed and actual == wanted
        else:
            confirmed = confirmed and math.isclose(float(actual), float(wanted), rel_tol=1e-9)
    return result(confirmed, "Read the created 3D contact feature back.", feature=created, definition=stored,
                  requested=requested, components=names, features=_features(study),
                  count=int(value(study, "GetMotionFeaturesCount")))


@tool("solve_motion_study", "Activate a motion study, run the native Calculate, then read the results object back: out-of-date flag plus sampled kinematics of a component.",
      {"name": NAME, "component": {"type": "string", "minLength": 1},
       "sample_times": {"type": "array", "items": {"type": "number", "minimum": 0}, "minItems": 2}}, ["name"])
def solve_motion_study(args):
    manager = _manager()
    study = _study(manager, _name(args["name"]))
    info = _info(study)
    if not _activate(manager, study):
        return result(False, "Could not activate the study before calculating.", study=info)
    started = time.monotonic()
    accepted = bool(value(study, "Calculate"))
    elapsed = round(time.monotonic() - started, 3)
    features = int(value(study, "GetMotionFeaturesCount"))
    data = {"study": _info(study), "native_accepted": accepted, "elapsed_sec": elapsed, "motion_features": features}
    results = _results(study, info["type_code"])
    if results is None:
        return result(False, "The native calculation produced no results object for this study type.", **data)
    out_of_date = bool(value(results, "IsOutOfDate"))
    data["out_of_date"] = out_of_date
    _, doc = active_document()
    component = _component(doc, args.get("component"))
    if component is not None:
        times = _sample_times(study, args.get("sample_times"))
        samples = _sample(results, component, times)
        data["component"] = str(safe(component, "Name2", ""))
        data["samples"] = samples
        data["motion_detected"] = _moved(samples)
    if not accepted:
        return result(False, "The native calculation was refused.", **data)
    if out_of_date:
        return result(False, "The native results object still reports the study as out of date.", **data)
    if info["type_code"] in SIMULATION_TYPES and features and not data.get("motion_detected", False):
        return result(False, "The native calculation returned true, but no sampled displacement or velocity "
                             "changed for the probed component.", **data)
    return result(True, "Calculated the motion study and read the results state back.", **data)


@tool("get_motion_study_results", "Read-only: per-time native motion results for one component (centre-of-mass position, linear and angular velocity/acceleration, Euler angles).",
      {"name": NAME, "component": {"type": "string", "minLength": 1},
       "times": {"type": "array", "items": {"type": "number", "minimum": 0}, "minItems": 1}}, ["name", "times"])
def get_motion_study_results(args):
    manager = _manager()
    study = _study(manager, _name(args["name"]))
    info = _info(study)
    _, doc = active_document()
    component = _component(doc, args.get("component"))
    if component is None:
        return result(False, "The active document has no top-level component to probe.", study=info)
    results = _results(study, info["type_code"])
    if results is None:
        return result(False, "The native MotionManager returned no results object for this study type.", study=info)
    times = _sample_times(study, args["times"])
    samples = _sample(results, component, times)
    return result(True, "Read native motion results.", study=info, component=str(safe(component, "Name2", "")),
                  out_of_date=bool(value(results, "IsOutOfDate")), samples=samples)


@tool("set_motion_study_animation", "Create or replace a native animation sequence on a motion study: rotate the model, explode or collapse, then read the resulting timeline back.",
      {"name": NAME, "action": {"type": "string", "enum": ["rotate_model", "explode", "collapse"]},
       "duration_sec": {"type": "number", "exclusiveMinimum": 0},
       "start_time_sec": {"type": "number", "minimum": 0, "default": 0},
       "delete_existing": {"type": "boolean", "default": True},
       "axis": {"type": "string", "enum": ["x", "y", "z"], "default": "y"},
       "revolutions": {"type": "integer", "minimum": 1, "default": 1},
       "direction": {"type": "string", "enum": ["clockwise", "counterclockwise"], "default": "clockwise"}},
      ["name", "action", "duration_sec"])
def set_motion_study_animation(args):
    action = str(args["action"])
    duration = float(args["duration_sec"])
    start = float(args.get("start_time_sec", 0))
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(start) or start < 0:
        raise RuntimeError("Animation duration must be positive and the start time non-negative.")
    delete_existing = bool(args.get("delete_existing", True))
    manager = _manager()
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before creating the animation.", study=_info(study))
    if action == "rotate_model":
        axis = {"x": 0, "y": 1, "z": 2}[str(args.get("axis", "y")).lower()]
        direction = {"clockwise": 0, "counterclockwise": 1}[str(args.get("direction", "clockwise")).lower()]
        accepted = bool(study.CreateByRotateModel(delete_existing, axis, int(args.get("revolutions", 1)),
                                                  direction, duration, start))
    elif action == "explode":
        accepted = bool(study.CreateByExplode(delete_existing, duration, start))
    else:
        accepted = bool(study.CreateByCollapse(delete_existing, duration, start))
    info = _info(study)
    end = round(start + duration, 6)
    covered = info["duration_sec"] + 1e-6 >= end
    return result(accepted and covered, "Read back the created animation timeline.", study=info,
                  action=action, expected_end_sec=end, native_accepted=accepted)


@tool("control_motion_study_playback", "Read or set the native animation play mode and start or stop playback, reporting the actual IsPlaying state.",
      {"name": NAME, "play_mode": {"type": "string", "enum": list(PLAY_MODES)},
       "action": {"type": "string", "enum": ["none", "play", "stop"], "default": "none"},
       "from_start": {"type": "boolean", "default": False},
       "time_sec": {"type": "number", "minimum": 0}}, ["name"])
def control_motion_study_playback(args):
    manager = _manager()
    study = _study(manager, _name(args["name"]))
    before = {"play_mode": int(value(study, "PlayMode")), "playing": bool(value(study, "IsPlaying"))}
    accepted = True
    mode = before["play_mode"]
    if "play_mode" in args:
        requested = str(args["play_mode"])
        study.PlayMode = PLAY_MODES[requested]
        mode = int(value(study, "PlayMode"))
        accepted = accepted and mode == PLAY_MODES[requested]
    action = str(args.get("action", "none"))
    if action == "play" and not before["playing"]:
        if "time_sec" in args:
            study.SetTime(float(args["time_sec"]))
        elif bool(args.get("from_start", False)):
            study.SetTime(0.0)
        accepted = bool(value(study, "Play")) and accepted
        time.sleep(0.3)
    elif action == "stop" and before["playing"]:
        accepted = bool(value(study, "Stop")) and accepted
        time.sleep(0.3)
    playing = bool(value(study, "IsPlaying"))
    expected = {"play": True, "stop": False}.get(action)
    return result(accepted and (expected is None or playing == expected),
                  "Read back animation playback state.", play_mode=mode, playing=playing,
                  previous=before, action=action)


@tool("export_motion_study_frames", "Render a motion study through the native animator to an image series or a movie file and verify the files that appear next to the output path.",
      {"name": NAME, "path": {"type": "string", "description": "Output file path under the MCP output root; image series append -NNNN."},
       "format": {"type": "string", "enum": sorted(FRAME_FORMATS), "default": "png"},
       "frame_per_second": {"type": "number", "exclusiveMinimum": 0, "default": 7.5},
       "start_time_sec": {"type": "number", "minimum": 0},
       "end_time_sec": {"type": "number", "minimum": 0},
       "save_entire_animation": {"type": "boolean", "default": True},
       "renderer": {"type": "string", "enum": list(RENDERERS), "default": "screen"},
       "allow_overwrite": {"type": "boolean", "default": False}}, ["name", "path"])
def export_motion_study_frames(args):
    fmt = str(args.get("format", "png")).lower()
    if fmt not in FRAME_FORMATS:
        raise RuntimeError(f"Unknown animation format '{fmt}'.")
    allow_overwrite = bool(args.get("allow_overwrite", False))
    target = validated_output_path(str(args["path"]), {"." + name for name in FRAME_FORMATS},
                                   allow_overwrite=allow_overwrite)
    if target.suffix.lower() != f".{fmt}":
        raise RuntimeError(f"The output path must end with '.{fmt}'.")
    existing = sorted(target.parent.glob(f"{target.stem}-*{target.suffix}"))
    if existing and not allow_overwrite:
        raise RuntimeError(f"Refusing to overwrite {len(existing)} existing frames next to {target}.")
    frame_per_second = float(args.get("frame_per_second", 7.5))
    if not math.isfinite(frame_per_second) or frame_per_second <= 0:
        raise RuntimeError("Frame rate must be a finite positive number.")
    manager = _manager()
    study = _study(manager, _name(args["name"]))
    if not _activate(manager, study):
        return result(False, "Could not activate the study before rendering.", study=_info(study))
    parameters = value(manager, "CreateAVIParameter")
    if parameters is None:
        return result(False, "SOLIDWORKS returned no animation parameter object.")
    parameters.FramePerSecond = frame_per_second
    parameters.SaveEntireAnimation = bool(args.get("save_entire_animation", True))
    parameters.OutputType = FRAME_FORMATS[fmt]
    parameters.RendererType = RENDERERS[str(args.get("renderer", "screen"))]
    if "start_time_sec" in args:
        parameters.StartTime = float(args["start_time_sec"])
    if "end_time_sec" in args:
        parameters.EndTime = float(args["end_time_sec"])
    accepted = bool(study.SaveToAVI(str(target), parameters))
    files = _await_files(target)
    sizes = {path.name: path.stat().st_size for path in files}
    data = {"study": _info(study), "path": str(target), "format": fmt, "native_accepted": accepted,
            "frame_per_second": float(value(parameters, "FramePerSecond")), "file_count": len(files),
            "files": sorted(sizes), "bytes": sum(sizes.values())}
    return result(bool(files), "Verified the rendered animation files on disk." if files else
                  "The native animator wrote no file for this format and renderer.", **data)
