# Copyright 2026 JIALE LIU
# Licensed under the Apache License, Version 2.0

"""Live rollback-bar regression on one newly-created disposable part."""

try:
    from .live_expansion_regression import call, near
except ImportError:  # direct script execution
    from live_expansion_regression import call, near


def run():
    original = call("list_open_documents")["active_title"]
    scratch = call("create_new_document", kind="part")["document"]["title"]
    try:
        call("create_sketch", plane="front", name="BaseProfile")
        call("draw_rectangle", x1_mm=0, y1_mm=0, x2_mm=10, y2_mm=10)
        call("close_sketch")
        call("boss_extrude", sketch_name="BaseProfile", depth_mm=10, name="BaseBoss")

        call("create_sketch", plane="front", name="ExtensionProfile")
        call("draw_rectangle", x1_mm=10, y1_mm=0, x2_mm=20, y2_mm=10)
        call("close_sketch")
        call("boss_extrude", sketch_name="ExtensionProfile", depth_mm=10, name="ExtensionBoss")
        near(call("get_mass_properties")["volume_mm3"], 2000, "full model volume")

        before = call("set_rollback_bar", position="before_feature", feature_name="ExtensionBoss")
        assert "ExtensionBoss" in before["rolled_back_features"], before
        near(call("get_mass_properties")["volume_mm3"], 1000, "rolled-back volume")

        after = call("set_rollback_bar", position="after_feature", feature_name="ExtensionBoss")
        assert "ExtensionBoss" not in after["rolled_back_features"], after
        near(call("get_mass_properties")["volume_mm3"], 2000, "rolled-forward volume")

        end = call("set_rollback_bar", position="end")
        assert end["rolled_back_features"] == [], end
        assert end["rebuilt"] and not end["problems"] and not end["saved"], end
        near(call("get_mass_properties")["volume_mm3"], 2000, "end-state volume")
        print("Rollback before/after/end and native IsRolledBack plus volume readback verified on a disposable part.", flush=True)
    finally:
        opened = {d["title"] for d in call("list_open_documents")["documents"]}
        if scratch in opened:
            call("close_document", name=scratch, discard_changes=True)
        if original in opened:
            call("activate_document", name=original)


if __name__ == "__main__":
    run()
