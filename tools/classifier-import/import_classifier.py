"""Offline, lossless import of the supplied v046 classifier. No runtime XLSX dependency."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
VERSION = "046-2024-11-15"
HEADER_SHA256 = "4980a2bc20e055cff1706ca7e5fb34e806328c6e640c1717887e4ec9be6c6bb0"

# Column identity, not header spelling, determines the recipient. Distinct endpoints
# (101, ODS PSC, MGPSS) remain distinct even under the merged MChS heading.
COLUMN_SERVICES = (
    "MCHS MCHS ODS_PSC ODS_PSC ODS_PSC ODS_PSC MGPSS POLICE POLICE POLICE "
    "AMBULANCE AMBULANCE AMBULANCE MOSGAZ MOSGAZ ZEMP ZEMP ZEMP ZEMP ZEMP "
    "FSB FSB MOSOBLGAZ AUTOROADS MOSGORTRANS MOSGORTRANS MOSGORTRANS GKH "
    "GORMOST GORMOST GORMOST GORMOST MOSCOW_CANAL MGTS MGTS METRO MOSVODOCANAL "
    "MOEK MOESK OEK MOSLIFT ZODD DEP_GKH MOSBEZ MOSBEZ_ANALYTICS MAYOR "
    "MOSCOLLECTOR MZD DEP_EDUCATION WATER_AUTHORITY MILITARY_COMMAND OATI "
    "MOSVODOSTOK DEPECO DEP_TSZN RSVO EVAZHD MSPPN RITUAL DTU ROSGVARDIA "
    "TERRITORIAL_OIV TINAO AUTOROADS_DISTRICT DEP_CONSTRUCTION DEP_CONSTRUCTION "
    "VETERINARY MOSZHILINSPECTION DEP_CULTURE GLINKA_CENTER NTU FSO MSR "
    "TOURISM DGP_INTEGRATION DGP_ARM112"
).split()
ALIASES = {s.casefold(): s for s in COLUMN_SERVICES}
ALIASES.update({"dep.tszn": "DEP_TSZN", "depeco": "DEPECO", "служба 101": "MCHS",
                "мчс": "MCHS", "служба 102": "POLICE", "мвд": "POLICE",
                "служба 103": "AMBULANCE", "смп": "AMBULANCE",
                "служба 104": "MOSGAZ", "мосгаз": "MOSGAZ"})


def normalize(value):
    if value is None:
        return None
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip() or None


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def stable_id(prefix, value):
    return prefix + "." + hashlib.sha256(encoded(value)).hexdigest()[:16]


def resolve_services(raw):
    if not normalize(raw):
        return []
    result = []
    for part in normalize(raw).split(","):
        key = normalize(part).casefold()
        if key not in ALIASES:
            raise ValueError(f"Unknown main service: {part!r}")
        result.append(ALIASES[key])
    return sorted(set(result))


def build_columns(headers):
    """Preserve exact selection branches; do not guess meanings of abbreviations."""
    def test(question, value):
        return {"questionId": question, "equals": value}

    nd = "routing.no-access"
    threat = "routing.threat-to-people"
    victims = "routing.victims-status"
    crime = "routing.offence"
    gas = "routing.gasification"
    med = "routing.medical-help"
    evac = "routing.evacuation"
    # Ambiguous source shorthand remains an explicitly review-required question.
    fsb = "routing.fsb-source-condition"
    transport = "routing.transport-victims"
    blocked = "routing.traffic-blocked"
    tunnel, pedestrian, auto = "routing.tunnel", "routing.pedestrian", "routing.auto"
    construction = "routing.construction"
    conditions = {
        "O": [test(nd, False)], "P": [test(nd, True)],
        "Q": [test(nd, False), test(threat, False), test(victims, "NONE")],
        "R": [test(threat, True)], "S": [test(victims, "PRESENT")], "T": [test(nd, True)],
        "V": [test(crime, False), test(victims, "NONE")],
        "W": [test(crime, True)], "X": [test(victims, "PRESENT")],
        "Y": [test(victims, "NONE")], "Z": [test(victims, "PRESENT")],
        "AA": [test(victims, "NOT_ON_SCENE")],
        "AB": [test(gas, False)], "AC": [test(gas, True)],
        "AD": [test(threat, False), test(victims, "NONE"), test(med, False), test(evac, False)],
        "AE": [test(threat, True)], "AF": [test(victims, "PRESENT")],
        "AG": [test(med, True)], "AH": [test(evac, True)],
        "AI": [test(fsb, False)], "AJ": [test(fsb, True)],
        "AM": [test(transport, False), test(blocked, False)],
        "AN": [test(transport, True)], "AO": [test(blocked, True)],
        "AQ": [test(tunnel, False), test(pedestrian, False), test(auto, False)],
        "AR": [test(tunnel, True)], "AS": [test(pedestrian, True)], "AT": [test(auto, True)],
        "AW": [test("routing.communication-facility", True)],
        "CA": [test(construction, False)], "CB": [test(construction, True)],
        "CE": [test("routing.culture-listed-facility", True)],
    }
    review = {"AI", "AJ", "AQ", "AS", "AT", "CE"}
    questions = {}
    labels = {
        nd: "Нет доступа", threat: "Угроза людям", victims: "Пострадавшие / погибшие",
        crime: "Правонарушение", gas: "Газификация", med: "Медицинская помощь",
        evac: "Требуется эвакуация", fsb: ">5 чел / ОД (значение требует уточнения)",
        transport: "Пострадавшие / погибшие (Мосгортранс)", blocked: "Перекрытие движения",
        tunnel: "Тоннель", pedestrian: "пеш (сокращение из источника)",
        auto: "ав (сокращение из источника)", construction: "Стройка",
        "routing.communication-facility": "На объектах связи",
        "routing.culture-listed-facility": "Объект из перечня (перечень не приложен)",
    }
    columns = []
    assert len(COLUMN_SERVICES) == 76
    for index, service in enumerate(COLUMN_SERVICES, 15):
        letter = get_column_letter(index)
        terms = conditions.get(letter, [])
        for term in terms:
            qid = term["questionId"]
            questions.setdefault(qid, {
                "id": qid, "label": labels[qid], "inputType": "SINGLE_SELECT",
                "options": ([{"id": "NONE", "label": "Признак не выбран"},
                             {"id": "PRESENT", "label": "Пострадавшие"},
                             {"id": "NOT_ON_SCENE", "label": "Пострадавшие не на месте"}]
                            if qid == victims else [{"id": "YES", "label": "Да", "value": True},
                                                   {"id": "NO", "label": "Нет", "value": False}]),
                "requiresReview": False,
            })
            if letter in review:
                questions[qid]["requiresReview"] = True
        columns.append({"sourceColumn": letter, "serviceId": service,
                        "sourceHeaders": [row[index - 1] for row in headers],
                        "condition": {"all": terms}, "requiresReview": letter in review})
    return columns, list(questions.values())


def import_workbook(path):
    raw_book = load_workbook(path, data_only=False)
    cached_book = load_workbook(path, data_only=True)
    try:
        if raw_book.sheetnames != ["Лист1"]:
            raise ValueError("Expected the v046 worksheet Лист1 only")
        sheet, cached = raw_book.active, cached_book.active
        if sheet.max_column != 90:
            raise ValueError("Expected 90 columns; classifier layout changed")
        raw_rows = list(sheet.values)
        cached_rows = list(cached.values)
        headers = [list(row) for row in raw_rows[:3]]
        if hashlib.sha256(encoded(headers)).hexdigest() != HEADER_SHA256:
            raise ValueError("Classifier headers changed; review column mappings before importing")
        if any(r.min_row > 3 for r in sheet.merged_cells.ranges):
            raise ValueError("Unexpected merged data cells; refusing implicit forward fill")
        columns, questions = build_columns(headers)
        services = {}
        for col in columns:
            sid = col["serviceId"]
            # Display labels are explicit metadata, never comparison keys.
            services.setdefault(sid, {"id": sid, "displayName": sid})
        display = {"MCHS": "Служба 101 (МЧС)", "ODS_PSC": "ОДС ПСЦ", "MGPSS": "МГПСС",
                   "POLICE": "Служба 102 (МВД)", "AMBULANCE": "Служба 103 (СМП)",
                   "MOSGAZ": "МОСГАЗ"}
        current_heading = None
        for col in columns:
            if col["sourceHeaders"][0]:
                current_heading = normalize(col["sourceHeaders"][0])
            sid = col["serviceId"]
            services[sid]["displayName"] = display.get(sid, current_heading or sid)
        for sid, label in {"MOSBEZ_ANALYTICS": "МОСБЕЗ — МКП, Аналитика", "DGP_INTEGRATION": "ДГП — интеграция",
                           "DGP_ARM112": "ДГП — АРМ-112"}.items():
            services[sid]["displayName"] = label
        records, warnings, signs, sections = [], [], {}, []
        seen_codes = set()
        section = None
        for row_number, (raw, cache) in enumerate(zip(raw_rows[3:], cached_rows[3:]), 4):
            row = [normalize(v) for v in cache]
            if all(v is None for v in row):
                continue
            if not any(v is not None for v in raw[:4]) and row[5] and not any(row[6:14]):
                section = row[5]
                sections.append({"label": section, "sourceRow": row_number,
                                 "routingNotes": [{"column": get_column_letter(i + 1), "rawValue": raw[i]}
                                                  for i in range(14, 90) if row[i]]})
                continue
            if not row[10] or not row[6]:
                raise ValueError(f"Row {row_number}: missing incident type or first sign")
            parts = raw[:4]
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v for v in parts):
                raise ValueError(f"Row {row_number}: invalid code components {parts}")
            g, a, b, c = map(int, parts)
            if not (1 <= g <= 99 and all(0 <= v <= 99 for v in (a, b)) and 0 <= c <= 999):
                raise ValueError(f"Row {row_number}: code components out of range")
            code = str(g * 1000000 + a * 10000 + b * 100 + c)
            expected_formula = f"=A{row_number}*1000000+B{row_number}*10000+C{row_number}*100+D{row_number}"
            if isinstance(raw[4], str) and raw[4].startswith("="):
                if raw[4] != expected_formula:
                    raise ValueError(f"Row {row_number}: unexpected code formula")
                if cache[4] is not None and str(cache[4]) != code:
                    raise ValueError(f"Row {row_number}: cached code differs from components")
            elif str(raw[4]) != code:
                raise ValueError(f"Row {row_number}: code differs from components")
            if code in seen_codes:
                raise ValueError(f"Row {row_number}: duplicate classifier code {code}")
            seen_codes.add(code)
            source = {"sheet": sheet.title, "row": row_number}
            issues = []
            def warn(kind):
                issues.append(kind)
                warnings.append({"code": kind, "classifierCode": code, **source})
            if c > 99:
                warn("OVERFLOW_SIGN_COMPONENT")
            levels, parent = [], None
            for level, label in enumerate(row[6:9], 1):
                if label is None:
                    levels.append(None)
                    if level == 2 and row[8] is not None:
                        warn("MISSING_INTERMEDIATE_SIGN")
                    continue
                sid = stable_id("sign", [g, level, parent, label])
                signs.setdefault(sid, {"id": sid, "level": level, "label": label, "parentId": parent})
                levels.append(sid)
                parent = sid
            response = row[12]
            status = "CODE"
            if response is None:
                status = "MISSING"
                warn("MISSING_RESPONSE_SCENARIO")
            elif response.casefold() == "без сценария":
                status, response = "EXPLICIT_NONE", None
            elif not re.fullmatch(r"\d+_\d+", response):
                status = "SOURCE_LABEL"
                warn("NON_CODE_RESPONSE_SCENARIO")
            if row[11] is None:
                warn("MISSING_EKP35")
            main_ids = resolve_services(raw[13])
            if not main_ids:
                warn("MISSING_MAIN_SERVICE")
            rules = []
            for idx, col in enumerate(columns, 14):
                value = row[idx]
                if value is None:
                    continue
                if isinstance(raw[idx], str) and raw[idx].startswith("="):
                    raise ValueError(f"Row {row_number}: unexpected formula in routing column")
                rules.append({"id": f"classifier.{code}.{col['sourceColumn']}",
                              "column": col["sourceColumn"],
                              "action": "DO_NOT_NOTIFY" if value.casefold() == "нет реагирования" else "NOTIFY",
                              "destinationIncidentType": None if value.casefold() == "нет реагирования" else value,
                              "rawValue": raw[idx],
                              "requiresReview": bool(re.search(r"услов|если|добавля|при наличии|по согласован", value, re.I))})
                if rules[-1]["requiresReview"]:
                    warn("REVIEW_INLINE_CONDITION_" + col["sourceColumn"])
                if col["requiresReview"]:
                    warn("REVIEW_ROUTING_CONDITION_" + col["sourceColumn"])
            question_ids = sorted({t["questionId"] for col in columns
                                   if any(rule["column"] == col["sourceColumn"] for rule in rules)
                                   for t in col["condition"]["all"]})
            additional = row[9]
            if additional:
                qid = stable_id("question.source", [code, additional])
                questions.append({"id": qid, "label": additional, "inputType": "TEXT",
                                  "options": [], "requiresReview": True})
                question_ids.append(qid)
                warn("REVIEW_ADDITIONAL_QUESTION")
            records.append({"classifierCode": code, "codeComponents": [g, a, b, c],
                            "section": section, "statisticalGroup": row[5],
                            "signIds": levels, "additionalSignsText": additional,
                            "questionIds": question_ids, "incidentType": row[10],
                            "ekp35IncidentType": row[11], "responseScenarioCode": response,
                            "responseScenarioStatus": status, "mainServiceIds": main_ids,
                            "routingRules": rules, "source": {**source, "rawFields": list(raw[5:14])},
                            "warnings": sorted(set(issues))})
        if not records:
            raise ValueError("Classifier has no incident records")
        catalog = {"schemaVersion": "1.0.0", "classifierVersion": VERSION,
                   "source": {"fileName": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "date": "2024-11-15", "sheet": sheet.title},
                   "services": sorted(services.values(), key=lambda x: x["id"]),
                   "sections": sections, "columns": columns, "questions": sorted(questions, key=lambda x: x["id"]),
                   "signs": sorted(signs.values(), key=lambda x: x["id"]), "records": records}
        report = {"classifierVersion": VERSION, "sourceSha256": catalog["source"]["sha256"],
                  "records": len(records), "missingResponseScenario": sum(r["responseScenarioStatus"] == "MISSING" for r in records),
                  "explicitNoScenario": sum(r["responseScenarioStatus"] == "EXPLICIT_NONE" for r in records),
                  "missingMainServices": sum(not r["mainServiceIds"] for r in records),
                  "noResponseRules": sum(rule["action"] == "DO_NOT_NOTIFY" for r in records for rule in r["routingRules"]),
                  "duplicateCodes": [], "unknownServices": [], "warnings": warnings}
        return catalog, report
    finally:
        raw_book.close()
        cached_book.close()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep one catalog record per line: deterministic diffs without multi-megabyte lines.
    if isinstance(value, dict) and ("records" in value or "warnings" in value):
        entries = []
        for key, item in value.items():
            body = ("[\n" + ",\n".join("    " + encoded(v).decode("utf-8") for v in item) + "\n  ]"
                    if isinstance(item, list) and item else encoded(item).decode("utf-8"))
            entries.append("  " + json.dumps(key) + ": " + body)
        text = "{\n" + ",\n".join(entries) + "\n}\n"
    else:
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_bytes(text.encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "contracts/catalog")
    args = parser.parse_args()
    try:
        catalog, report = import_workbook(args.source)
        schema = json.loads((ROOT / "contracts/classifier.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(catalog)
        write_json(args.output_dir / "classifier-v046-11.json", catalog)
        write_json(args.output_dir / "classifier-v046-11.report.json", report)
    except Exception as exc:
        # Import failures must leave no newly published partial catalog.
        print(f"Classifier import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in report.items() if k != "warnings"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
