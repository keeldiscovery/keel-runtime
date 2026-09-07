#!/usr/bin/env python3
"""Generates the bundled scripted-executor script from keel-cloud's frozen golden corpus.

Spec `001-scripted-executor`'s `AMENDMENT-measured-beliefs.md`, RT-004. The bundled script is
**never written by hand**: it is one corpus entry's one stage, turned into the result shapes
keel-cloud's `screenContracts export` currently serves, so that `--executor scripted` with no
`--script` answers a real screen with a real belief set instead of failing at the first job with
a schema error.

    python3 tools/generate_bundled_script.py \
        --corpus ../keel-cloud/canon/designs/measured-beliefs/corpus/01-countly.yaml \
        --stage PROBLEM \
        --out keel_runtime/testing/scripts/countly-problem.json

This is a developer tool, not part of the package: it imports `yaml`, and the runtime itself
stays standard-library-only. The corpus is read and never written -- if a value cannot be
carried across, this refuses by name rather than inventing one.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

# The corpus writes a tap the way a person reads it; the wire wants the enum name. Same table
# keel-e2e-eval's `instructions/context.py` carries, and for the same reason: this is the only
# place the two vocabularies meet.
TAP_ENUM = {
    "hasn't happened": "HASNT_HAPPENED",
    "it hasn't happened": "HASNT_HAPPENED",
    "can't recall": "CANT_RECALL",
    "rather not say": "RATHER_NOT_SAY",
}

STATEMENT_SCREEN = {
    "PROBLEM": ("problem", "PROBLEM_FRAME", "PROBLEM_ASSUMPTIONS"),
    "SOLUTION": ("solution", "SOLUTION_FRAME", "SOLUTION_ASSUMPTIONS"),
    "COMMERCIAL": ("commercial", "COMMERCIAL_FRAME", "COMMERCIAL_ASSUMPTIONS"),
}


def expectation_for(belief: dict) -> dict:
    """The belief's expectation, verbatim, minus the keys the corpus writes as `null`.

    The corpus records an open-ended band as `lower: null` and a per-less measure as
    `per: null`; the wire's schema types those fields as an object and a string, so a null
    fails validation. Dropping a null key is not editing the corpus's meaning -- an absent
    bound and a null bound are the same claim -- and it is the only transformation this
    generator makes to an expectation.
    """
    expectation = {k: v for k, v in belief["expectation"].items() if v is not None}
    measure = expectation.get("measure")
    if isinstance(measure, dict):
        expectation["measure"] = {k: v for k, v in measure.items() if v is not None}
    return expectation


class Refusal(RuntimeError):
    """A value the corpus does not carry. Named, never invented."""


def tap_enum(tap):
    if tap is None:
        return None
    key = str(tap).strip().lower()
    if key not in TAP_ENUM:
        raise Refusal(f"tap {tap!r} is outside the table")
    return TAP_ENUM[key]


def build(entry: dict, stage: str) -> dict:
    statement_key, frame_screen, assumptions_screen = STATEMENT_SCREEN[stage]

    statement = (entry.get("statements") or {}).get(statement_key)
    if not statement:
        raise Refusal(f"{entry['id']} carries no {statement_key} statement")

    roles = {role["id"]: role for role in entry.get("roles") or []}
    beliefs = [b for b in entry.get("beliefs") or [] if b.get("stage") == stage]
    anchors = [a for a in (entry.get("questionnaire") or {}).get("anchors") or []
               if a.get("stage") == stage]
    if not beliefs:
        raise Refusal(f"{entry['id']} has no beliefs on {stage}")

    # Every selection this stage's questionnaire actually offers -- a belief naming any other
    # is a refusal, not a guess.
    offered = {s["id"] for anchor in anchors for s in anchor.get("selections") or []}

    assumptions, introduced = [], set()
    for belief in beliefs:
        if belief.get("selection") not in offered:
            raise Refusal(
                f"{entry['id']} belief {belief['id']} names selection "
                f"{belief.get('selection')!r}, which no {stage} anchor offers")
        role_id = belief.get("askedOf")
        role = roles.get(role_id)
        if role is None:
            raise Refusal(f"{entry['id']} belief {belief['id']} is askedOf unknown role {role_id!r}")
        # The wire has no `askedOf`: the first belief to name a role introduces it, every later
        # one reuses it by label.
        if role_id in introduced:
            role_field = {"reuse": role["label"]}
        else:
            introduced.add(role_id)
            role_field = {"new": {"label": role["label"], "roleType": role["roleType"],
                                  "about": role["about"]}}
        assumption = {
            "heading": belief["heading"],
            "statement": belief["statement"],
            "risk": belief["risk"],
            "mark": belief["mark"],
            "expectation": expectation_for(belief),
            "selection": belief["selection"],
            "role": role_field,
        }
        if belief.get("founderPhrase"):
            assumption["founderPhrase"] = belief["founderPhrase"]
        assumptions.append(assumption)

    questionnaire_anchors = []
    for anchor in anchors:
        written = {"id": anchor["id"], "prompt": anchor["prompt"],
                   "selections": [
                       {k: v for k, v in selection.items() if k != "stage"}
                       for selection in anchor.get("selections") or []]}
        if anchor.get("taps"):
            written["taps"] = [tap_enum(t) for t in anchor["taps"]]
        questionnaire_anchors.append(written)

    anchor_ids = {a["id"] for a in anchors}
    interpret = []
    for answer in entry.get("answers") or []:
        anchorings = []
        for anchor_id, written in (answer.get("anchors") or {}).items():
            if anchor_id not in anchor_ids:
                continue
            if not (written.get("text") or "").strip():
                continue  # a blank anchor is never in the context, so never in the answer
            anchoring = written.get("anchoring")
            if anchoring not in ("ANCHORED", "GUESSED"):
                raise Refusal(
                    f"{entry['id']} person {answer['person']!r} wrote under {anchor_id} but the "
                    f"corpus records anchoring {anchoring!r}")
            anchorings.append({"stage": stage, "anchorId": anchor_id, "anchoring": anchoring})
        if anchorings:
            interpret.append({"outcome": "COMPLETED",
                              "result": {"anchorings": anchorings, "unprompted": [], "flags": []}})

    return {
        frame_screen: [{"outcome": "COMPLETED", "result": {"statement": statement}}],
        assumptions_screen: [{
            "outcome": "COMPLETED",
            "result": {
                "assumptions": assumptions,
                "questionnaire": {
                    "introduction": (
                        f"{entry['title'].split('—')[0].strip()} would like to ask you about "
                        "something that happened recently. There are no right answers."),
                    "anchors": questionnaire_anchors,
                },
                "normalization_rationale": (
                    f"Every line is measured against what the founder said, in the units this "
                    f"market uses. Taken verbatim from the frozen corpus entry {entry['id']}."),
            },
        }],
        "INTERPRET": interpret,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--stage", default="PROBLEM", choices=sorted(STATEMENT_SCREEN))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--keel-cloud-commit", default="unknown")
    args = parser.parse_args()

    entry = yaml.safe_load(args.corpus.read_text(encoding="utf-8"))
    script = build(entry, args.stage)

    out = {
        "_description": (
            f"The {args.stage} stage of keel-cloud's frozen golden corpus entry "
            f"{entry['id']} ({entry['title']}), in the result shapes keel-cloud's "
            "screenContracts export currently serves. The bundled default for "
            "`--executor scripted` with no --script."),
        "_source": f"keel-cloud canon/designs/measured-beliefs/corpus/{args.corpus.name}",
        "_keel_cloud_commit": args.keel_cloud_commit,
        "_generated_by": "tools/generate_bundled_script.py -- never hand-edited",
        "_generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out.update(script)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: "
          f"{', '.join(k for k in script)} "
          f"({len(script['INTERPRET'])} INTERPRET entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
