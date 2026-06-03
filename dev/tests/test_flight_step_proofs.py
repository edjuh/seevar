#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.flight import pilot
from core.flight.pilot import AcquisitionTarget, DiamondSequence, PointingProof
from core.flight import fsm as fsm_module
from core.flight.fsm import SovereignFSM
from core.flight.pilot import FrameResult, TelemetryBlock


class FakeTelescope:
    # Function: FakeTelescope.__init__
    def __init__(self, *, tracking=False, slewing=False, atpark=False):
        self.tracking = tracking
        self.slewing = slewing
        self.atpark = atpark
        self.set_tracking_calls = 0

    # Function: FakeTelescope.safe_get
    def safe_get(self, prop, default=None):
        return {
            "tracking": self.tracking,
            "slewing": self.slewing,
            "atpark": self.atpark,
        }.get(prop, default)

    # Function: FakeTelescope.set_tracking
    def set_tracking(self, on):
        self.set_tracking_calls += 1
        self.tracking = bool(on)


class FakeCamera:
    # Function: FakeCamera.__init__
    def __init__(self, state):
        self._state = state

    @property
    # Function: FakeCamera.camera_state
    def camera_state(self):
        return self._state


# Function: _sequence
def _sequence(telescope=None, camera=None):
    seq = object.__new__(DiamondSequence)
    seq._telescope = telescope or FakeTelescope()
    seq._camera = camera or FakeCamera(pilot.AlpacaCamera.IDLE)
    seq._last_pointing_proof = None
    return seq


# Function: test_tracking_gate_enables_and_verifies_tracking
def test_tracking_gate_enables_and_verifies_tracking(monkeypatch):
    monkeypatch.setattr(pilot, "TRACKING_VERIFY_TIMEOUT_SEC", 0.2)
    monkeypatch.setattr(pilot, "TRACKING_VERIFY_INTERVAL_SEC", 0.01)
    telescope = FakeTelescope(tracking=False, slewing=False, atpark=False)
    seq = _sequence(telescope=telescope)

    seq._ensure_science_tracking()

    assert telescope.tracking is True
    assert telescope.set_tracking_calls == 1


# Function: test_camera_idle_gate_rejects_busy_camera
def test_camera_idle_gate_rejects_busy_camera(monkeypatch):
    monkeypatch.setattr(pilot, "CAMERA_IDLE_TIMEOUT_SEC", 0.01)
    seq = _sequence(camera=FakeCamera(pilot.AlpacaCamera.EXPOSING))

    with pytest.raises(RuntimeError, match="Camera not idle"):
        seq._ensure_camera_idle()


# Function: test_pointing_proof_must_match_target
def test_pointing_proof_must_match_target():
    seq = _sequence()
    target = AcquisitionTarget("ST Boo", 15.0, 35.0)
    seq._last_pointing_proof = PointingProof(
        target_name="ST Boo",
        ra_hours=15.0,
        dec_deg=35.0,
        verified_at_monotonic=pilot.time.monotonic(),
        error_arcmin=2.0,
    )

    assert seq._pointing_proof_matches(target)
    assert not seq._pointing_proof_matches(AcquisitionTarget("TT Boo", 15.0, 35.0))


class PartialSequence:
    # Function: PartialSequence.__init__
    def __init__(self):
        self.results = [
            FrameResult(success=True, path=Path("/tmp/ok.fits")),
            FrameResult(success=False, error="tracking proof failed"),
        ]

    # Function: PartialSequence.init_session
    def init_session(self):
        return TelemetryBlock()

    # Function: PartialSequence.prepare_target
    def prepare_target(self, target, telemetry=None, notify=None):
        return target

    # Function: PartialSequence.acquire
    def acquire(self, **_kwargs):
        return self.results.pop(0)


class FailFirstSequence:
    # Function: FailFirstSequence.__init__
    def __init__(self):
        self.calls = 0

    # Function: FailFirstSequence.init_session
    def init_session(self):
        return TelemetryBlock()

    # Function: FailFirstSequence.prepare_target
    def prepare_target(self, target, telemetry=None, notify=None):
        return target

    # Function: FailFirstSequence.acquire
    def acquire(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return FrameResult(success=False, error="trailed frame")
        return FrameResult(success=True, path=Path("/tmp/should_not_happen.fits"))


class SuccessSequence:
    # Function: SuccessSequence.init_session
    def init_session(self):
        return TelemetryBlock()

    # Function: SuccessSequence.prepare_target
    def prepare_target(self, target, telemetry=None, notify=None):
        return target

    # Function: SuccessSequence.acquire
    def acquire(self, **_kwargs):
        return FrameResult(success=True, path=Path("/tmp/ok.fits"))


class FakeProofRecorder:
    records = []

    # Function: FakeProofRecorder.__init__
    def __init__(self, target_name):
        self.target_name = target_name

    # Function: FakeProofRecorder.record
    def record(self, step, status, *, detail="", evidence_path=None, extra=None):
        self.records.append(
            {
                "target": self.target_name,
                "step": step,
                "status": status,
                "detail": detail,
                "evidence_path": str(evidence_path) if evidence_path else None,
            }
        )


# Function: test_fsm_rejects_partial_target_by_default
def test_fsm_rejects_partial_target_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(fsm_module, "STATE_FILE", tmp_path / "system_state.json")
    fsm = SovereignFSM()
    fsm.sequence = PartialSequence()

    ok = fsm.execute_target(AcquisitionTarget("ST Boo", 15.0, 35.0, n_frames=2), telemetry=TelemetryBlock())

    assert ok is False
    assert fsm.state == "ERROR"


# Function: test_strict_chain_stops_after_first_failed_frame
def test_strict_chain_stops_after_first_failed_frame(monkeypatch, tmp_path):
    monkeypatch.setattr(fsm_module, "STATE_FILE", tmp_path / "system_state.json")
    monkeypatch.setattr(fsm_module, "STRICT_TARGET_PROOF_CHAIN", True)
    sequence = FailFirstSequence()
    fsm = SovereignFSM()
    fsm.sequence = sequence

    ok = fsm.execute_target(AcquisitionTarget("ST Boo", 15.0, 35.0, n_frames=2), telemetry=TelemetryBlock())

    assert ok is False
    assert sequence.calls == 1


# Function: test_fsm_writes_proof_records
def test_fsm_writes_proof_records(monkeypatch, tmp_path):
    monkeypatch.setattr(fsm_module, "STATE_FILE", tmp_path / "system_state.json")
    FakeProofRecorder.records = []
    monkeypatch.setattr(fsm_module, "FlightProofRecorder", FakeProofRecorder)
    fsm = SovereignFSM()
    fsm.sequence = SuccessSequence()

    ok = fsm.execute_target(AcquisitionTarget("ST Boo", 15.0, 35.0, n_frames=1), telemetry=TelemetryBlock())

    assert ok is True
    assert {"target": "ST Boo", "step": "target", "status": "start", "detail": "n_frames=1", "evidence_path": None} in FakeProofRecorder.records
    assert any(row["step"] == "connect" and row["status"] == "pass" for row in FakeProofRecorder.records)
    assert any(row["step"] == "target_prepare" and row["status"] == "pass" for row in FakeProofRecorder.records)
    assert any(row["step"] == "accept" and row["status"] == "pass" and row["evidence_path"] == "/tmp/ok.fits" for row in FakeProofRecorder.records)
    assert any(row["step"] == "target" and row["status"] == "pass" for row in FakeProofRecorder.records)


# Function: test_fsm_builds_seestar_alp_adapter_only_when_controlled
def test_fsm_builds_seestar_alp_adapter_only_when_controlled(monkeypatch):
    monkeypatch.setattr(fsm_module, "_seestar_alp_control_enabled", lambda: False)
    assert isinstance(fsm_module._build_sequence(), DiamondSequence)


class FakeSSalpClient:
    # Function: FakeSSalpClient.__init__
    def __init__(self, *, image_path="last.fit"):
        self.tracking = False
        self.image_path = image_path
        self.slew = None

    # Function: FakeSSalpClient.test_connection_sync
    def test_connection_sync(self):
        return {"ok": True}

    # Function: FakeSSalpClient.goto_target_sync
    def goto_target_sync(self, target_name, ra, dec, is_j2000=True):
        self.slew = (target_name, ra, dec, is_j2000)
        return {"ok": True}

    # Function: FakeSSalpClient.scope_get_track_state_sync
    def scope_get_track_state_sync(self):
        return {"tracking": self.tracking}

    # Function: FakeSSalpClient.scope_set_track_state_sync
    def scope_set_track_state_sync(self, enabled):
        self.tracking = bool(enabled)
        return {"tracking": self.tracking}

    # Function: FakeSSalpClient.start_solve_sync
    def start_solve_sync(self):
        return {"started": True}

    # Function: FakeSSalpClient.get_solve_result_sync
    def get_solve_result_sync(self):
        return {"solved": True}

    # Function: FakeSSalpClient.start_stack_sync
    def start_stack_sync(self, gain, restart=True):
        return {"gain": gain, "restart": restart}

    # Function: FakeSSalpClient.get_last_image_sync
    def get_last_image_sync(self, is_subframe=True, is_thumb=False):
        return {"path": self.image_path}


# Function: test_seestar_alp_adapter_proves_slew_solve_track_capture
def test_seestar_alp_adapter_proves_slew_solve_track_capture(monkeypatch):
    from core.flight.seestar_alp_adapter import SeestarAlpSequence

    monkeypatch.setattr(
        "core.flight.seestar_alp_adapter.load_config",
        lambda: {"seestar_alp": {"base_url": "http://127.0.0.1:5555"}, "seestars": []},
    )
    client = FakeSSalpClient()
    sequence = SeestarAlpSequence(client=client)
    result = sequence.acquire(AcquisitionTarget("ST Boo", 15.0, 35.0))

    assert result.success is True
    assert result.path == Path("last.fit")
    assert client.slew == ("ST Boo", 15.0, 35.0, True)
    assert client.tracking is True


# Function: test_seestar_alp_adapter_fails_without_image_path
def test_seestar_alp_adapter_fails_without_image_path(monkeypatch):
    from core.flight.seestar_alp_adapter import SeestarAlpSequence

    monkeypatch.setattr(
        "core.flight.seestar_alp_adapter.load_config",
        lambda: {"seestar_alp": {"base_url": "http://127.0.0.1:5555"}, "seestars": []},
    )
    sequence = SeestarAlpSequence(client=FakeSSalpClient(image_path=""))
    result = sequence.acquire(AcquisitionTarget("ST Boo", 15.0, 35.0))

    assert result.success is False
    assert "no image path" in result.error
