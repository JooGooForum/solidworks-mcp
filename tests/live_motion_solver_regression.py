# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for details.

"""Live MotionManager solver/animation checks; scratch documents only.

Fixtures stay under SW_MCP_OUTPUT_ROOT/.motion-tests/<uuid>.  The script records
what the installed Motion components actually do: on builds without the
SOLIDWORKS Motion solver the study type switch and the motion samples are
reported as unavailable instead of being asserted as working.
"""

import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live_expansion_regression import call, near
from solidworks_mcp.sw_core import (
    HANDLERS, OUTPUT_ROOT, as_list, byref_long, running_app, value,
)


def raw(tool_name, **args):
    payload = HANDLERS[tool_name](args)
    print(f"{'PASS' if payload['ok'] else 'FAIL'} {tool_name}: {payload.get('message')}", flush=True)
    return payload


def fixture(folder: Path):
    call("create_new_document", kind="part")
    call("create_sketch", plane="front", name="Base")
    call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=10, y2_mm=10)
    call("close_sketch")
    call("boss_extrude", sketch_name="Base", depth_mm=10)
    near(call("get_mass_properties")["volume_mm3"], 1000, "fixture volume")
    part = folder / "block.SLDPRT"
    call("save_document", path=str(part))
    return part


def main():
    app = running_app()
    initial = {str(value(document, "GetTitle")) for document in as_list(value(app, "GetDocuments"))}
    original = str(value(app.ActiveDoc, "GetTitle")) if app.ActiveDoc is not None else ""
    folder = OUTPUT_ROOT / ".motion-tests" / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    try:
        part = fixture(folder)
        part_refusal = raw("add_motion_gravity", name="MCP Part Probe", strength=9.81, axis="y")
        assert not part_refusal["ok"] and part_refusal["data"]["document_type"] == "part", part_refusal
        print("Part documents refuse motion elements with a documented reason instead of a COM fault.", flush=True)
        assembly = call("create_new_document", kind="assembly")["document"]["title"]
        inserted = call("insert_component", path=str(part))
        component = inserted["component"]
        call("set_component_fixed", component_names=[component], fixed=False)
        call("activate_document", name=assembly)

        created = call("create_motion_study", name="MCP Solve", type="animation")["study"]
        supported = created["supported_types"]
        print(f"Supported study types reported: {supported}", flush=True)
        switched = call("set_motion_study_type", name="MCP Solve", type="basic_motion")["study"]
        assert switched["type"] == "basic_motion", switched
        refused = raw("set_motion_study_type", name="MCP Solve", type="motion_analysis")
        assert not refused["ok"], refused
        assert refused["data"]["study"]["type"] == "basic_motion", refused
        print("Motion Analysis study type is refused by this session; recorded as a gap.", flush=True)

        timing = call("set_motion_study_timing", name="MCP Solve", duration_sec=1.0, time_sec=0)["study"]
        near(timing["duration_sec"], 1.0, "study duration")

        gravity = call("add_motion_gravity", name="MCP Solve", strength=9.81, axis="y", reverse_direction=False)
        assert gravity["feature"]["type"] == "AEMGravity", gravity
        near(gravity["definition"]["strength"], 9.81, "gravity strength")
        assert gravity["definition"]["axis"] == 1 and gravity["definition"]["reverse_direction"] is False, gravity
        assert gravity["count"] == 1, gravity

        listed = call("list_motion_features", name="MCP Solve")
        assert listed["count"] == 1 and listed["features"][0]["name"] == gravity["feature"]["name"], listed
        assert isinstance(listed["external_motors"], int) and isinstance(listed["external_forces"], int), listed

        edges = call("list_edges")["edges"]
        assert len(edges) >= 2, edges
        linear = call("add_motion_motor", name="MCP Solve", motor_type="linear",
                      direction={"edges": [0]}, speed=25.0)
        assert linear["feature"]["type"] == "AEMLinearMotor", linear
        assert linear["definition"] == {"speed": 25.0, "reverse_direction": False, "motor_type": 0}, linear
        rotary = call("add_motion_motor", name="MCP Solve", motor_type="rotational",
                      direction={"edges": [1]}, speed=30.0, reverse_direction=True)
        assert rotary["feature"]["type"] == "AEMRotationalMotor", rotary
        assert rotary["definition"] == {"speed": 30.0, "reverse_direction": True, "motor_type": 1}, rotary
        everything = call("list_motion_features", name="MCP Solve")
        assert everything["count"] == 3, everything
        assert {entry["type"] for entry in everything["features"]} == {"AEMGravity", "AEMLinearMotor", "AEMRotationalMotor"}, everything

        solved = raw("solve_motion_study", name="MCP Solve", sample_times=[0.0, 0.5, 1.0])
        data = solved["data"]
        assert data["native_accepted"] is True, data
        assert data["out_of_date"] is False, data
        assert isinstance(data["motion_detected"], bool), data
        assert solved["ok"] == data["motion_detected"], data
        print(f"Sampled motion detected={data['motion_detected']} on component {data.get('component')}; "
              f"solve verdict ok={solved['ok']}.", flush=True)

        results = call("get_motion_study_results", name="MCP Solve", component=component, times=[0.0, 0.5, 1.0])
        assert [sample["time_sec"] for sample in results["samples"]] == [0.0, 0.5, 1.0], results
        first = results["samples"][0]
        assert all(len(first[key]) == 3 for key in ("position_mm", "linear_velocity_mm_per_s",
                                                   "linear_acceleration_mm_per_s2")), first
        assert results["out_of_date"] in (True, False), results

        call("create_motion_study", name="MCP Anim", type="animation")
        animation = call("set_motion_study_animation", name="MCP Anim", action="rotate_model",
                         duration_sec=2.0, start_time_sec=0)
        near(animation["study"]["duration_sec"], 2.0, "animation duration")
        for action in ("explode", "collapse"):
            payload = raw("set_motion_study_animation", name="MCP Anim", action=action, duration_sec=1.0,
                          start_time_sec=0, delete_existing=False)
            covered = payload["data"]["study"]["duration_sec"] + 1e-6 >= payload["data"]["expected_end_sec"]
            assert payload["ok"] == (payload["data"]["native_accepted"] and covered), payload

        frames = raw("export_motion_study_frames", name="MCP Anim", path=str(folder / "frames.png"),
                     format="png", frame_per_second=7.5)
        if frames["ok"]:
            assert frames["data"]["file_count"] >= 1 and frames["data"]["bytes"] > 0, frames
            for name in frames["data"]["files"]:
                assert (folder / name).stat().st_size > 0, name
            print(f"Rendered {frames['data']['file_count']} PNG frames "
                  f"({frames['data']['bytes']} bytes).", flush=True)
        else:
            print("PNG series rendering is unavailable in this session; recorded as a gap.", flush=True)
        movie = raw("export_motion_study_frames", name="MCP Anim", path=str(folder / "movie.avi"),
                    format="avi", frame_per_second=7.5)
        if not movie["ok"]:
            assert movie["data"]["file_count"] == 0, movie
            print("AVI encoding is refused by this session; recorded as a gap.", flush=True)

        playback = raw("control_motion_study_playback", name="MCP Anim", play_mode="loop",
                       action="play", from_start=True)
        if playback["ok"]:
            assert playback["data"]["play_mode"] == 2 and playback["data"]["playing"] is True, playback
            stopped = call("control_motion_study_playback", name="MCP Anim", action="stop")
            assert stopped["playing"] is False, stopped
        else:
            print("Animation playback could not be started in this session; recorded as a gap.", flush=True)

        call("delete_motion_study", name="MCP Solve")
        call("delete_motion_study", name="MCP Anim")
        print(f"Motion tools verified on {assembly} with {len(edges)} selectable edges.", flush=True)
    finally:
        documents = list(call("list_open_documents")["documents"])
        documents.sort(key=lambda entry: entry["document_type"] != "assembly")
        for document in documents:
            if document["title"] not in initial:
                HANDLERS["close_document"]({"name": document["title"], "discard_changes": True})
        for document in list(call("list_open_documents")["documents"]):
            if document["title"] not in initial:
                HANDLERS["close_document"]({"name": document["title"], "discard_changes": True})
        remaining = [entry["title"] for entry in call("list_open_documents")["documents"]]
        if original and original in remaining:
            call("activate_document", name=original)
        print("REMAINING " + json.dumps(remaining, ensure_ascii=False), flush=True)
        assert set(remaining) <= initial, remaining


if __name__ == "__main__":
    main()
