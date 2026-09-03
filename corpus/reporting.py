import json


def report_as_json(report):
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)


def report_as_text(report):
    lines = [
        f"Mode: {report['mode']}",
        (
            f"Mapping: {report['mapping']['name']} "
            f"(version {report['mapping']['version']})"
        ),
        f"Workbook: {report['source']['filename']}",
        f"SHA-256: {report['source']['sha256']}",
        "",
        "Sheets:",
    ]
    for sheet_name, sheet in report["sheets"].items():
        detail = (
            f"  {sheet_name}: physical={sheet['physical_rows']}, "
            f"meaningful={sheet['meaningful_rows']}, blank={sheet['blank_rows']}, "
            f"role={sheet['role']}"
        )
        if sheet.get("ignored"):
            detail += ", intentionally ignored"
        lines.append(detail)
        lines.append(
            "    proposed canonical questions={canonical}, legacy observations={legacy}, "
            "provenance rows={provenance}, ignored meaningful rows={ignored}".format(
                canonical=sheet.get("candidate_canonical_questions", 0),
                legacy=sheet.get("candidate_legacy_observations", 0),
                provenance=sheet.get("provenance_rows", 0),
                ignored=sheet.get("ignored_meaningful_rows", 0),
            )
        )
        if sheet.get("ignored_reason"):
            lines.append(f"    reason: {sheet['ignored_reason']}")
        if sheet.get("separator_rows"):
            lines.append(f"    structural separators: {sheet['separator_rows']}")
        if sheet.get("unused_rows"):
            lines.append(f"    unused blank rows: {sheet['unused_rows']}")
    lines.extend(("", "Domain reconciliation:"))
    for domain in report["domains"]:
        lines.append(
            f"  {domain['code']}: {domain['name']} rows "
            f"{domain['start_row']}-{domain['end_row']}, source="
            f"{domain['meaningful_source_rows']}, merges={domain['merged_source_rows']}, "
            f"questions={domain['question_count']}, IDs={domain['first_id']}..."
            f"{domain['last_id']}, {domain['reconciliation']}"
        )
    lines.extend(("", "Tag reconciliation:"))
    for tag in report["tags"]:
        lines.append(f"  {tag['name']}: {tag['reconciliation']}")
    lines.extend(("", f"Canonical Questions ({len(report['questions'])}):"))
    for question in report["questions"]:
        rows = ",".join(str(row) for row in question["source_rows"])
        lines.append(
            f"  {question['stable_id']} {question['sheet_name']} rows [{rows}] "
            f"domain={question['domain_slug']}, {question['reconciliation']}: "
            f"{question['question_text']}"
        )
    lines.extend(
        ("", f"Legacy observations ({len(report['legacy_observations'])}):")
    )
    for observation in report["legacy_observations"]:
        canonical = observation["question_stable_id"] or "unlinked"
        judgment = observation["legacy_judgment"] or "unknown"
        lines.append(
            f"  {observation['sheet_name']} row {observation['row_number']} "
            f"canonical={canonical}, judgment={judgment}: "
            f"{observation['source_question_text']}"
        )
    lines.extend(("", "Summary:"))
    for name, value in report["summary"].items():
        lines.append(f"  {name}: {value}")
    lines.extend(("", "Reconciliation changes:"))
    for name, value in report["changes"].items():
        lines.append(f"  {name}: {value}")
    lines.extend(("", f"Warnings ({len(report['warnings'])}):"))
    for warning in report["warnings"]:
        rows = ",".join(str(row) for row in warning["source_rows"])
        lines.append(
            f"  {warning['code']} {warning['sheet_name']} rows [{rows}]: "
            f"{warning['explanation']}"
        )
    if report["conflicts"]:
        lines.extend(("", f"Conflicts ({len(report['conflicts'])}):"))
        for conflict in report["conflicts"]:
            lines.append(
                f"  {conflict['code']} {conflict['object']}: {conflict['explanation']}"
            )
    if report.get("already_applied"):
        lines.append("")
        lines.append(f"Existing import batch reused: {report['existing_batch_id']}")
    if report.get("applied") is True:
        lines.append("")
        lines.append(f"Applied transactionally as batch {report['batch_id']}.")
    elif report.get("applied") is False:
        lines.append("")
        lines.append(f"No-op: batch {report['batch_id']} already contains this import.")
    return "\n".join(lines)
