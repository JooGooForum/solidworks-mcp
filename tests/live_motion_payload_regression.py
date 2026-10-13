# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Live MotionManager payload checks: force, torque, springs, dampers and 3D contact.

Fixtures stay under SW_MCP_OUTPUT_ROOT/.motion-payload/<uuid>.  Every element is
created between two real component faces/edges of a scratch assembly, and the
study's own feature list decides whether the native feature really appeared.
"""

import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_expansion_regression import call, near
from solidworks_mcp.sw_core import HANDLERS, OUTPUT_ROOT, as_list, running_app, value


def raw(tool_name, **args):
    payload = HANDLERS[tool_name](args)
    print(f"{'PASS' if payload['ok'] else 'FAIL'} {tool_name}: {payload.get('message')}", flush=True)
    return payload


def main():
    app = running_app()
    initial = {str(value(document, "GetTitle")) for document in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    folder = OUTPUT_ROOT / ".motion-payload" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    try:
        part_paths = []
        for label in ("left", "right"):
            call("create_new_document", kind="part")
            call("create_sketch", plane="front", name="Base")
            call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=10, y2_mm=10)
            call("close_sketch")
            call("boss_extrude", sketch_name="Base", depth_mm=10)
            near(call("get_mass_properties")["volume_mm3"], 1000, f"{label} fixture volume")
            path = folder / f"{label}.SLDPRT"
            call("save_document", path=str(path))
            call("close_document", name=call("list_open_documents")["active_title"], discard_changes=True)
            part_paths.append(path)

        assembly = call("create_new_document", kind="assembly")["document"]["title"]
        components = []
        for path in part_paths:
            component = call("insert_component", path=str(path))["component"]
            call("set_component_fixed", component_names=[component], fixed=False)
            components.append(component)

        call("create_motion_study", name="Payload", type="basic_motion")
        faces = call("list_faces")["faces"]
        candidates = sorted(faces, key=lambda entry: entry["point_mm"][0])
        face_pair = [{"faces": [candidates[0]["index"]]}, {"faces": [candidates[-1]["index"]]}]
        edges = call("list_edges")["edges"]
        edge_pair = [{"edges": [edges[0]["index"]]}, {"edges": [edges[-1]["index"]]}]

        force = call("add_motion_force", name="Payload", force_type="linear", magnitude=10.0,
                     reverse_direction=False, references=face_pair)
        assert force["feature"]["type"] == "AEMLinearForce", force
        assert force["definition"]["force_type"] == 0, force
        near(force["definition"]["magnitude"], 10.0, "linear force magnitude")

        torque = call("add_motion_force", name="Payload", force_type="torque", magnitude=5.0,
                      reverse_direction=True, references=edge_pair)
        assert torque["feature"]["type"] == "AEMTorque", torque
        assert torque["definition"]["force_type"] == 1 and torque["definition"]["reverse_direction"] is True, torque
        near(torque["definition"]["magnitude"], 5.0, "torque magnitude")

        spring = call("add_motion_spring", name="Payload", spring_type="linear", spring_constant=1.0,
                      free_length=0.05, references=face_pair)
        assert spring["feature"]["type"] == "AEMLinearSpring", spring
        near(spring["definition"]["spring_constant"], 1.0, "linear spring constant")
        near(spring["definition"]["free_length"], 0.05, "linear spring free length")

        torsional = call("add_motion_spring", name="Payload", spring_type="torsional", spring_constant=2.0,
                         references=edge_pair)
        assert torsional["feature"]["type"] == "AEMTorsionalSpring", torsional
        near(torsional["definition"]["spring_constant"], 2.0, "torsional spring constant")

        coil = call("add_motion_spring", name="Payload", spring_type="linear_motion", spring_constant=1.0,
                    coil_diameter=0.01, number_of_coils=3, wire_diameter=0.001, references=edge_pair)
        assert coil["feature"]["type"] == "AEMLinearSpring", coil
        assert coil["definition"]["number_of_coils"] == 3, coil

        coil_torsion = raw("add_motion_spring", name="Payload", spring_type="torsional_motion",
                           spring_constant=1.0, coil_diameter=0.01, number_of_coils=3,
                           wire_diameter=0.001, references=edge_pair)
        if coil_torsion["ok"]:
            assert coil_torsion["definition"]["number_of_coils"] == 3, coil_torsion
        else:
            assert coil_torsion["data"]["definition"]["number_of_coils"] in (-1, 0), coil_torsion
            print("Torsional coil springs ignore the coil geometry on this build; recorded as a gap.", flush=True)

        damper = call("add_motion_damper", name="Payload", damper_type="linear", damping_constant=0.5,
                      references=face_pair)
        assert damper["feature"]["type"] == "AEMLinearDamper", damper
        near(damper["definition"]["damping_constant"], 0.5, "linear damping constant")

        torsional_damper = call("add_motion_damper", name="Payload", damper_type="torsional",
                                damping_constant=0.75, references=edge_pair)
        assert torsional_damper["feature"]["type"] == "AEMTorsionalDamper", torsional_damper
        near(torsional_damper["definition"]["damping_constant"], 0.75, "torsional damping constant")

        contact = call("add_motion_contact", name="Payload", components=components, stiffness=100000.0,
                       exponent=2.0, max_damping=1000.0, penetration=0.0001,
                       friction_option="full", use_restitution=True, restitution=0.3)
        assert contact["feature"]["type"] == "AEM3DContact", contact
        near(contact["definition"]["stiffness"], 100000.0, "contact stiffness")
        assert contact["definition"]["friction_option"] == 1, contact
        near(contact["definition"]["restitution"], 0.3, "contact restitution")

        listed = call("list_motion_features", name="Payload")
        types = [entry["type"] for entry in listed["features"]]
        print(f"Payload features ({listed['count']}): {json.dumps(types, ensure_ascii=False)}", flush=True)
        for expected in ("AEMLinearForce", "AEMTorque", "AEMLinearSpring", "AEMTorsionalSpring",
                         "AEMLinearDamper", "AEMTorsionalDamper", "AEM3DContact"):
            assert expected in types, types
        call("delete_motion_study", name="Payload")
        print(f"Motion payload tools verified on {assembly} with components {components}.", flush=True)
    finally:
        for _ in range(2):
            documents = list(call("list_open_documents")["documents"])
            documents.sort(key=lambda entry: entry["document_type"] != "assembly")
            for document in documents:
                if document["title"] not in initial:
                    HANDLERS["close_document"]({"name": document["title"], "discard_changes": True})
        remaining = [entry["title"] for entry in call("list_open_documents")["documents"]]
        if original and original in remaining:
            call("activate_document", name=original)
        print("REMAINING " + json.dumps(remaining, ensure_ascii=False), flush=True)
        assert set(remaining) <= initial, remaining


if __name__ == "__main__":
    main()
