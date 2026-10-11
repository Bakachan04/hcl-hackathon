import json
import re
from typing import Any, Dict, List, Set, Tuple

try:
    from app import llm
except ImportError:
    from . import llm


SYSTEM_PROMPT = """You are an AI assistant explaining production schedule replanning to a plant manager.
Instructions:
1. Write 3 to 6 short, direct sentences explaining what happened and why.
2. Use ONLY the verified facts provided below. Do NOT assume, extrapolate, or invent any orders, machines, operators, times, or numbers.
3. If requested information is absent from the facts, explicitly say that it is not available in the data.
4. Never create schedules or modify solver results.
"""


def _extract_fact_entities(facts: Any) -> Tuple[Set[str], Set[str], Set[str], Set[str], Set[float], Set[str]]:
    """Recursively extract known identifiers, clock times, and numbers from facts."""
    order_ids: Set[str] = set()
    machine_ids: Set[str] = set()
    operator_ids: Set[str] = set()
    clock_times: Set[str] = set()
    numbers: Set[float] = set()
    raw_number_strings: Set[str] = set()

    def _normalize_time(t: str) -> str:
        parts = t.split(":")
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{parts[1]}"
        return t

    def _walk(obj: Any):
        if obj is None:
            return
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump()
        elif hasattr(obj, "dict"):
            obj = obj.dict()

        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                _walk(item)
        elif isinstance(obj, (int, float)):
            f_val = float(obj)
            numbers.add(f_val)
            raw_number_strings.add(str(obj))
            if isinstance(obj, float) and obj.is_integer():
                raw_number_strings.add(str(int(obj)))
        elif isinstance(obj, str):
            # Extract identifiers
            for oid in re.findall(r"\bO-\d+\b", obj):
                order_ids.add(oid)
            for mid in re.findall(r"\b[A-Z]{2,}-\d+\b", obj):
                if not mid.startswith("OP-") and not mid.startswith("O-"):
                    machine_ids.add(mid)
            for opid in re.findall(r"\bOP-\d+\b", obj):
                operator_ids.add(opid)
            for ct in re.findall(r"\b\d{1,2}:\d{2}\b", obj):
                clock_times.add(_normalize_time(ct))

            # Also find dates and numbers in strings
            for num in re.findall(r"\b\d+(?:\.\d+)?\b", obj):
                try:
                    numbers.add(float(num))
                    raw_number_strings.add(num)
                except ValueError:
                    pass

    _walk(facts)
    return order_ids, machine_ids, operator_ids, clock_times, numbers, raw_number_strings


def check_facts(text: str, facts: Dict[str, Any]) -> Dict[str, Any]:
    """Verify that every order ID, machine ID, operator ID, clock time, and number

    in the text appears in facts.
    Returns: {"ok": bool, "unknown_items": list[str]}
    """
    (
        known_orders,
        known_machines,
        known_operators,
        known_times,
        known_numbers,
        known_num_strs,
    ) = _extract_fact_entities(facts)

    unknown_items: List[str] = []

    def _normalize_time(t: str) -> str:
        parts = t.split(":")
        if len(parts) == 2:
            return f"{int(parts[0]):02d}:{parts[1]}"
        return t

    # 1. Check order IDs
    text_orders = set(re.findall(r"\bO-\d+\b", text))
    for o in text_orders:
        if o not in known_orders:
            unknown_items.append(o)

    # 2. Check machine IDs
    text_machines = set(re.findall(r"\b[A-Z]{2,}-\d+\b", text))
    for m in text_machines:
        if m.startswith("OP-") or m.startswith("O-"):
            continue
        if m not in known_machines:
            unknown_items.append(m)

    # 3. Check operator IDs
    text_operators = set(re.findall(r"\bOP-\d+\b", text))
    for op in text_operators:
        if op not in known_operators:
            unknown_items.append(op)

    # 4. Check clock times
    text_times = set(re.findall(r"\b\d{1,2}:\d{2}\b", text))
    for ct in text_times:
        norm = _normalize_time(ct)
        if norm not in known_times:
            unknown_items.append(ct)

    # 5. Check numbers (mask out already checked entities and dates first)
    masked_text = text
    # Mask order IDs, machine IDs, operator IDs
    for item in list(text_orders) + list(text_machines) + list(text_operators):
        masked_text = re.sub(rf"\b{re.escape(item)}\b", " ", masked_text)

    # Mask full dates (e.g. 2026-10-12)
    masked_text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", masked_text)

    # Mask times (e.g. 06:00)
    for t in text_times:
        masked_text = re.sub(rf"\b{re.escape(t)}\b", " ", masked_text)

    # Find standalone numbers
    raw_numbers = re.findall(r"\b\d+(?:\.\d+)?\b", masked_text)
    for num_str in set(raw_numbers):
        # Ignore common harmless English sentence counts or bullet indices if they match 1 to 6
        try:
            val = float(num_str)
            is_known = (
                num_str in known_num_strs
                or any(abs(val - kn) < 1e-4 for kn in known_numbers)
            )
            if not is_known:
                unknown_items.append(num_str)
        except ValueError:
            unknown_items.append(num_str)

    return {
        "ok": len(unknown_items) == 0,
        "unknown_items": sorted(unknown_items),
    }


def _build_deterministic_explanation(facts: Dict[str, Any]) -> str:
    """Build a completely faithful plant-manager explanation directly from verified facts."""
    kpis = facts.get("kpis", {})
    if hasattr(kpis, "model_dump"):
        kpis = kpis.model_dump()
    elif hasattr(kpis, "dict"):
        kpis = kpis.dict()

    changes = facts.get("changes", [])
    check = facts.get("check", {})
    if hasattr(check, "model_dump"):
        check = check.model_dump()
    elif hasattr(check, "dict"):
        check = check.dict()

    sentences: List[str] = [
        "The production schedule has been replanned to accommodate disruptions."
    ]

    # Changes sentence
    if changes:
        change_summaries = []
        for ch in changes[:3]:
            if hasattr(ch, "model_dump"):
                ch = ch.model_dump()
            elif hasattr(ch, "dict"):
                ch = ch.dict()
            oid = ch.get("order_id", "order")
            m_from = ch.get("from") or ch.get("from_", "")
            m_to = ch.get("to", "")
            reason = ch.get("reason_code", "disruption")
            if m_from and m_to:
                change_summaries.append(f"{oid} moved from {m_from} to {m_to} ({reason})")
            else:
                change_summaries.append(f"{oid} updated ({reason})")
        sentences.append(
            f"A total of {len(changes)} job changes were made, including: {', '.join(change_summaries)}."
        )
    else:
        sentences.append("All jobs remain on their scheduled machines without modifications.")

    # KPI sentence
    late = kpis.get("late_orders", 0)
    lateness_h = kpis.get("total_lateness_h", 0.0)
    overtime_h = kpis.get("overtime_h", 0.0)
    changeovers = kpis.get("changeovers", 0)

    sentences.append(
        f"The replanned schedule results in {late} late orders ({lateness_h}h total lateness), "
        f"{overtime_h}h of overtime, and {changeovers} changeovers."
    )

    # Validation sentence
    all_ok = check.get("all_ok", True)
    if all_ok:
        sentences.append("All machine capacity, operator skill, and routing precedence constraints are fully satisfied.")
    else:
        violations = check.get("violations", [])
        sentences.append(f"Validation identified {len(violations)} constraint issue(s) in the proposed plan.")

    return " ".join(sentences)


def explain(facts: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Explain schedule changes to a plant manager using only verified facts.

    Validates generated explanation against check_facts; retries once on hallucination,
    and returns a deterministic faithful explanation if validation fails.
    """
    user_prompt = f"Verified Facts:\n{json.dumps(facts, default=str, indent=2)}\n\nExplain the schedule changes and KPIs to the plant manager in 3 to 6 short sentences."

    text, usage = llm.complete(SYSTEM_PROMPT, user_prompt)
    fact_check = check_facts(text, facts)

    if fact_check["ok"]:
        usage["fact_check_passed"] = True
        return text, usage

    # Retry once with explicit notification of unknown items
    retry_prompt = (
        f"{user_prompt}\n\n"
        f"CRITICAL ERROR: Your previous response contained unverified items not present in the facts: "
        f"{fact_check['unknown_items']}. Rewrite your response using strictly verified numbers and identifiers from the facts."
    )
    retry_text, retry_usage = llm.complete(SYSTEM_PROMPT, retry_prompt)
    retry_check = check_facts(retry_text, facts)

    total_calls = usage.get("llm_calls", 0) + retry_usage.get("llm_calls", 0)
    total_tokens = usage.get("tokens", 0) + retry_usage.get("tokens", 0)

    if retry_check["ok"]:
        return retry_text, {
            "llm_calls": total_calls,
            "tokens": total_tokens,
            "fact_check_passed": True,
            "retried": True,
        }

    # Second failure: return completely faithful deterministic template
    fallback_text = _build_deterministic_explanation(facts)
    return fallback_text, {
        "llm_calls": total_calls,
        "tokens": total_tokens,
        "fact_check_passed": False,
        "fallback": True,
        "unknown_items": retry_check["unknown_items"],
    }

