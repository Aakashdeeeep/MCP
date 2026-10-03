"""Steps that use an earlier step's result: "find the nearest temple, then put it in the calendar".

Still one plan, compiled once. The planner may give a task `depends_on: ["t1"]` and use
`{{t1.address}}` inside a string argument. Two halves, both pure code:

  check_dependencies(tasks)  at planning time. Every reference must point at a real task in
                             the same plan, at a field that task's tool ALWAYS returns (the
                             registry's `returns`), with no cycles. Anything else becomes a
                             "please repeat" task, exactly like any other invalid step.

  resolve(task, task_state)  at run time, inside that task's Map iteration. It reads the
                             results already recorded in PlanHistory and fills the
                             placeholders in, or says to wait, or says the step is blocked
                             because what it needed failed or was not approved.

Values are filled in BEFORE the zone gate, so a caregiver approving a calendar event sees the
real address, never "{{t1.address}}". Only data flows between steps, never instructions:
a value lands inside an argument that code has already type-checked as a string.

A Zone 3 task never waits for anything: its dependencies are removed at planning time.
"""
import json
import re

from raksha_common.tool_registry import get_tool

# {{t1.address}} - task ids are already normalised to [0-9A-Za-z_-] by the planner
PLACEHOLDER = re.compile(r"\{\{\s*([0-9A-Za-z_-]+)\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

DONE = {"done"}
DEAD = {"failed", "not_approved", "skipped", "expired"}  # the value will never arrive

# Wait between checks: quick at first (most steps finish in seconds), then slow, because the
# step being waited on may itself be waiting up to an hour for the family's approval.
FAST_WAIT_SECONDS, FAST_CHECKS = 3, 20
SLOW_WAIT_SECONDS = 30
MAX_CHECKS = FAST_CHECKS + (65 * 60) // SLOW_WAIT_SECONDS  # outlives the 1h approval timeout

BLOCKED_REPLY_HI = "यह काम पिछले काम पर टिका था, जो पूरा नहीं हो पाया, इसलिए इसे अभी नहीं किया।"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def references(args):
    """{(task_id, field)} referenced anywhere in the args."""
    return {match for value in (args or {}).values() for text in _strings(value) for match in PLACEHOLDER.findall(text)}


def _has_cycle(graph):
    visiting, done = set(), set()

    def visit(node):
        if node in done:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        if any(visit(dep) for dep in graph.get(node, ())):
            return True
        visiting.discard(node)
        done.add(node)
        return False

    return {node for node in graph if visit(node)}


def check_dependencies(tasks, invalid):
    """Validate the data flow of a whole plan. `invalid(task_id, reason)` builds the
    replacement for a task that cannot run. Returns the new task list."""
    by_id = {task["task_id"]: task for task in tasks}
    problems = {}
    graph = {}

    for task in tasks:
        tid = task["task_id"]
        refs = references(task.get("args"))
        deps = [d for d in dict.fromkeys(task.get("depends_on") or []) if d != tid]

        if task.get("zone") == 3:
            # a panic alert never waits; any placeholder text is left as plain words
            graph[tid] = []
            continue

        # a reference implies a dependency, even if the model forgot to list it
        deps = list(dict.fromkeys(deps + [ref_id for ref_id, _ in sorted(refs)]))
        for dep in deps:
            if dep == tid:
                problems[tid] = "a step cannot depend on itself"
            elif dep not in by_id:
                problems[tid] = f"depends on a step that is not in the plan ({dep})"
        for ref_id, field in refs:
            if ref_id == tid:
                problems[tid] = "a step cannot use its own result"
                continue
            source = by_id.get(ref_id)
            if source is None:
                continue  # already reported above
            returns = (get_tool(source["agent"], source["tool"]) or {}).get("returns") or []
            if field not in returns:
                problems[tid] = f"uses {ref_id}.{field}, but {source['agent']}.{source['tool']} does not return {field}"
        graph[tid] = [d for d in deps if d in by_id and d != tid]

    for tid in _has_cycle(graph):
        problems.setdefault(tid, "steps depend on each other in a circle")

    depended_on = {dep for deps in graph.values() for dep in deps}
    result = []
    for task in tasks:
        tid = task["task_id"]
        if tid in problems:
            result.append(invalid(tid, problems[tid]))
            continue
        task = {**task, "depends_on": graph[tid]}
        if tid in depended_on:
            task["has_dependents"] = True  # a re-plan must keep this tool, so the fields still exist
        result.append(task)

    # a task whose dependency was just invalidated can never run either
    removed = set(problems)
    changed = True
    while changed:
        changed = False
        for i, task in enumerate(result):
            if task.get("depends_on") and removed.intersection(task["depends_on"]) and task["task_id"] not in removed:
                removed.add(task["task_id"])
                result[i] = invalid(task["task_id"], "depends on a step that could not be planned")
                changed = True
    return result


def _fill(value, results):
    if isinstance(value, list):
        return [_fill(item, results) for item in value]
    if not isinstance(value, str):
        return value

    def substitute(match):
        field_value = results[match.group(1)][match.group(2)]
        if isinstance(field_value, list):
            return ", ".join(map(str, field_value))
        return str(field_value)

    return PLACEHOLDER.sub(substitute, value)


def _result_of(state):
    if "result" in state and isinstance(state["result"], dict):
        return state["result"]
    try:
        return json.loads(state.get("result_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def resolve(task, task_state, attempt=0):
    """Returns {"state": "ready" | "waiting" | "blocked", ...}. Never raises.

    task_state is PlanHistory's task_state map: {task_id: {"status", "result_json"}}."""
    deps = task.get("depends_on") or []
    task_state = task_state or {}
    results = {}

    for dep in deps:
        state = task_state.get(dep) or {}
        status = state.get("status")
        if status in DEAD:
            return {"state": "blocked", "reason": f"{dep} {status.replace('_', ' ')}", "reply_text": BLOCKED_REPLY_HI}
        if status not in DONE:
            if attempt + 1 >= MAX_CHECKS:
                return {"state": "blocked", "reason": f"gave up waiting for {dep}", "reply_text": BLOCKED_REPLY_HI}
            wait = FAST_WAIT_SECONDS if attempt < FAST_CHECKS else SLOW_WAIT_SECONDS
            return {"state": "waiting", "attempt": attempt + 1, "wait_seconds": wait, "waiting_for": dep}
        results[dep] = _result_of(state)

    for ref_id, field in references(task.get("args")):
        if field not in results.get(ref_id, {}):
            return {"state": "blocked", "reason": f"{ref_id} did not return {field}", "reply_text": BLOCKED_REPLY_HI}

    args = {name: _fill(value, results) for name, value in (task.get("args") or {}).items()}
    if references(args):  # a filled-in value must never smuggle in another placeholder
        return {"state": "blocked", "reason": "a value still contains a placeholder", "reply_text": BLOCKED_REPLY_HI}
    resolved = {**task, "args": args, "resolved_from": {dep: sorted(results[dep]) for dep in deps}}
    return {"state": "ready", "task": resolved}
