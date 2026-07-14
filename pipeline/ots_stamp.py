#!/usr/bin/env python3
"""
Phase 4 step 21: SHA-256 hash a file and anchor it via OpenTimestamps.

NOTE on implementation: the official `otsclient` CLI (`ots stamp`) is broken
on this machine - its `python-bitcoinlib` dependency unconditionally imports
`bitcoin.core.key` at module load, which calls ctypes.util.find_library('ssl')
and gets None (no discoverable OpenSSL on this Windows Python), and even
after pointing it at Git-for-Windows' bundled libssl-3-x64.dll, that DLL is
OpenSSL 3.x and no longer exports the legacy 1.0.x symbols
(`BN_add` etc.) the old bitcoinlib ctypes bindings expect. That code path is
only needed for `otsclient`'s local-Bitcoin-node verify/upgrade commands -
NOT for submitting a digest to the public calendar servers, which the
`opentimestamps` core package (already a dependency, pure Python) does on
its own. This module calls that directly, using the library's own
DetachedTimestampFile serialization - so the .ots file produced is a
genuine, spec-compliant OpenTimestamps proof, not a hand-rolled imitation.

`ots upgrade <file>.ots` (once python-bitcoinlib's import issue is worked
around, or run from a machine/WSL with real OpenSSL 1.1/3.x compat) will
later attach the actual Bitcoin block confirmation once the calendar
servers' aggregated timestamp is mined - that's expected to take hours,
not something this script waits for.
"""
import hashlib
from pathlib import Path

from opentimestamps.calendar import DEFAULT_AGGREGATORS, RemoteCalendar
from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
from opentimestamps.core.op import OpSHA256
from opentimestamps.core.serialize import BytesDeserializationContext, BytesSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp


def stamp_file(path: Path) -> tuple[Path, str]:
    """SHA-256 hash `path`, submit to OTS calendar servers, write path.ots. Returns (ots_path, sha256_hex)."""
    data = path.read_bytes()
    digest = hashlib.sha256(data).digest()

    ts = Timestamp(digest)
    submitted = 0
    for url in DEFAULT_AGGREGATORS:
        try:
            cal = RemoteCalendar(url)
            sub_ts = cal.submit(digest, timeout=30)
            ts.merge(sub_ts)
            submitted += 1
        except Exception as e:
            print(f"[warn] calendar {url} failed: {e}")

    if submitted == 0:
        raise RuntimeError("All OTS calendar servers failed - no timestamp proof created")

    dtf = DetachedTimestampFile(OpSHA256(), ts)
    ctx = BytesSerializationContext()
    dtf.serialize(ctx)

    ots_path = path.with_name(path.name + ".ots")
    ots_path.write_bytes(ctx.getbytes())
    return ots_path, digest.hex()


def _nodes_with_pending(ts: Timestamp):
    """Yield every sub-Timestamp node that has a PendingAttestation attached directly."""
    if any(isinstance(a, PendingAttestation) for a in ts.attestations):
        yield ts
    for sub_ts in ts.ops.values():
        yield from _nodes_with_pending(sub_ts)


def check_and_upgrade(ots_path: Path) -> dict:
    """Ask each pending calendar whether the digest has since been confirmed in a
    Bitcoin block. Re-writes the .ots file in place if any attestation upgraded.
    Returns {"confirmed_heights": [...], "pending_calendars": [...]}."""
    original_bytes = ots_path.read_bytes()
    ctx = BytesDeserializationContext(original_bytes)
    dtf = DetachedTimestampFile.deserialize(ctx)

    for node in list(_nodes_with_pending(dtf.timestamp)):
        for att in [a for a in node.attestations if isinstance(a, PendingAttestation)]:
            try:
                cal = RemoteCalendar(att.uri)
                new_ts = cal.get_timestamp(node.msg)
                node.merge(new_ts)
            except Exception:
                pass  # not confirmed yet, or calendar unreachable - not an error, just try again later

    check_ctx = BytesSerializationContext()
    dtf.serialize(check_ctx)
    upgraded = check_ctx.getbytes() != original_bytes  # only a REAL change - e.g. still-pending re-merges are no-ops

    if upgraded:
        out_ctx = BytesSerializationContext()
        dtf.serialize(out_ctx)
        ots_path.write_bytes(out_ctx.getbytes())

    confirmed_heights, pending_calendars = [], []
    for _, att in dtf.timestamp.all_attestations():
        if isinstance(att, BitcoinBlockHeaderAttestation):
            confirmed_heights.append(att.height)
        elif isinstance(att, PendingAttestation):
            pending_calendars.append(att.uri)

    return {"confirmed_heights": confirmed_heights, "pending_calendars": pending_calendars}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=str)
    args = ap.parse_args()
    ots_path, sha256_hex = stamp_file(Path(args.file))
    print(f"[OK] sha256={sha256_hex}")
    print(f"[OK] .ots proof written -> {ots_path}")
