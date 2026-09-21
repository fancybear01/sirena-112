"""Reference fixture evaluation, for tests only. Production evaluation belongs to Core #33."""
import json
import uuid
from pathlib import Path

from import_classifier import ROOT, write_json


def evaluate(catalog, record, answers):
    columns = {c["sourceColumn"]: c for c in catalog["columns"]}
    service_refs = {s["id"]: s for s in catalog["services"]}
    selected, denied, unresolved = {}, set(), []
    for rule in record["routingRules"]:
        column = columns[rule["column"]]
        terms = column["condition"]["all"]
        if any(t["questionId"] in answers and answers[t["questionId"]] != t["equals"] for t in terms):
            continue
        if any(t["questionId"] not in answers for t in terms) or column["requiresReview"] or rule["requiresReview"]:
            unresolved.append(rule["id"])
            continue
        sid = column["serviceId"]
        if rule["action"] == "DO_NOT_NOTIFY":
            denied.add(sid)
            continue
        selected.setdefault(sid, []).append({"ruleId": rule["id"],
            "message": f"Колонка {rule['column']}: {rule['destinationIncidentType']}",
            "matchedInputIds": [t["questionId"] for t in terms]})
    # Contradictory matched rules need review, not an invented global deny-wins policy.
    for sid in denied & selected.keys():
        unresolved.append("CONFLICT:" + sid)
    return ([{**service_refs[sid], "reasons": selected[sid]} for sid in sorted(selected) if sid not in denied],
            unresolved)


def build_examples(catalog):
    records = {r["classifierCode"]: r for r in catalog["records"]}
    refs = {s["id"]: s for s in catalog["services"]}
    result = {}
    for code, category in [("1050602", "FIRE"), ("2010000", "ACCIDENT"),
                           ("22010000", "MEDICAL"), ("14010100", "UTILITY")]:
        record = records[code]
        answers = {q["id"]: ("NONE" if q["id"] == "routing.victims-status" else False)
                   for q in catalog["questions"] if q["inputType"] == "SINGLE_SELECT"}
        answers["routing.victims-status"] = "PRESENT" if category in ("MEDICAL", "PERSON_AT_RISK") else "NONE"
        services, unresolved = evaluate(catalog, record, answers)
        if unresolved:
            raise ValueError(f"Fixture {code} has unresolved routing: {unresolved}")
        expected = {
            "incident": {"selectedSignIds": [s for s in record["signIds"] if s],
                         "answers": [{"questionId": q, "optionIds": [
                             ("YES" if answers[q] else "NO") if isinstance(answers[q], bool) else answers[q]]}
                                     for q in record["questionIds"] if q in answers]},
            "address": {"displayAddress": "Учебный адрес, дом 1"},
            "description": "Учебный пример: " + record["incidentType"],
            "victims": {"present": answers["routing.victims-status"] == "PRESENT"},
        }
        truth = {k: record[k] for k in ("classifierCode", "incidentType", "ekp35IncidentType",
                                       "responseScenarioCode", "responseScenarioStatus")}
        truth.update({"classifierVersion": catalog["classifierVersion"],
                      "mainServices": [refs[s] for s in record["mainServiceIds"]],
                      "requiredServices": services, "expectedInput": expected})
        result[code] = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "sirena112:classifier:" + code)),
                        "version": 3, "title": record["incidentType"], "category": category,
                        "difficulty": "BASIC", "timeLimitSeconds": 30,
                        "profile": "Синтетический интеграционный пример по классификатору. " + record["incidentType"],
                        "groundTruth": truth,
                        "rubric": {"criteria": [{"code": "SIGNS", "description": "Выбраны признаки из каталога",
                                                  "weight": 1, "critical": True}]}}
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "contracts/catalog/classifier-v046-11.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "contracts/examples")
    args = parser.parse_args()
    from jsonschema import Draft202012Validator, FormatChecker
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    examples = build_examples(catalog)
    schema = json.loads((ROOT / "contracts/scenario.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for example in examples.values():
        validator.validate(example)
    for code, example in examples.items():
        write_json(args.output_dir / f"scenario-{code}.json", example)


if __name__ == "__main__":
    main()
