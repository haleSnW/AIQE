[简体中文](multi-agent-testing.md) | [English](multi-agent-testing.en.md)

# Multi-Agent Testing Division of Labor and Task Sheet Template (Multi-Agent Testing)

> When quality evaluation is handed over to multiple agents working together, what it relies on is not "agents'
> self-discipline" but **clear role boundaries + verifiable task sheets**. This document defines a four-role testing
> division-of-labor model and a task sheet template, and ships with a directly reusable generic testing agent skill
> (`skills/testing-agent/`). This model draws on common practices in multi-agent collaboration (role boundaries +
> verifiable task sheets), with generalized wording.

---

## 1. The Four-Role Testing Division-of-Labor Model

| Role | Responsibility | Output | Boundary (forbidden) |
|---|---|---|---|
| **Planner** | Break down quality tasks, maintain progress, coordinate other roles, review deliverables | Task list + a task sheet for each task | Does not write test code directly; does not issue "passed" conclusions on behalf of the Executor |
| **Executor** | Implement test cases/scripts/fixes per the task sheet, doing only what is within the task sheet's boundaries | Code diff + smoke test results | No opportunistic refactoring; no changes to files outside the task sheet's scope; no skipping the acceptance commands in the task sheet |
| **Reviewer** | Independently review the Executor's deliverables: check item by item against the task sheet | Review checklist (pass/fail + precise location evidence) | Does not modify code on behalf of the Executor; no conclusions based on impressions — every conclusion carries file:line evidence |
| **QA** | Run the full acceptance suite (syntax/tests/interface consistency), output a pass/fail list | Acceptance report (with precise error information when failing) | Does not fix, only reports; does not expand the test scope beyond the task sheet on its own |

**Iron rules of collaboration**:
- **Role separation**: the Executor does not review its own deliverables, and the Planner does not adjudicate tasks it
  assigned itself — this is the premise of "tests being able to catch the tester's own mistakes".
- **The task sheet is a contract**: no task is assigned without a task sheet; the Executor does not invent acceptance
  commands absent from the task sheet, and the Reviewer does not require them.
- **QA is the last gate**: after a batch of tasks is completed, the QA role must run the full suite once, and the
  pass/fail list is archived with the batch.

## 2. Task Sheet Template

Every task is issued with a task sheet; all fields are required (they may be condensed to a single line, but none may be
missing):

```markdown
### Task Sheet T-<number>

- **Task**: one-sentence description (what to do, what not to do)
- **Source**: which requirement/defect/plan item this comes from (traceable upstream)
- **Boundary (scope)**:
  - Only modify these files/directories (path-exact)
  - Explicitly forbidden: no refactoring, no new dependencies, no protocol changes
- **Acceptance commands** (the executor MUST run each one and paste the output):
  ```
  <command 1, expected output>
  <command 2, expected output>
  ```
- **Timeout notice**: this task should be done within <duration>; beyond <duration>, stop digging in,
  return partial results and blockers, and let the planner decide whether to continue or downgrade
- **Deliverable format**: diff / file list / report path
```

**Requirements for writing acceptance commands**:
1. They must be executable by copy-paste, and must state the **expected output** (not "should pass", but comparable
   text such as `91 passed`);
2. They must be able to prove that "the task is really completed" — for example, for a bug-fixing task, the acceptance
   commands must include the full sequence of "first run red on the version where the bug still exists, then run green
   after the fix" (see the skill);
3. Acceptance commands involving real devices/networks are gated by default, noted as "report NOT_ASSESSED when there is
   no environment".

## 3. Task Sheet Example (Ready to Use by Changing Parameters)

```markdown
### Task Sheet T-014

- **Task**: add a "response contains sensitive information" branch to scoring, output WARN status
- **Source**: the five-state vocabulary of process-management.md (WARN use case)
- **Boundary**: only modify src/AIQE/judge.py and tests/test_runner.py;
  forbidden to modify protocol.py/schema.py or introduce new dependencies
- **Acceptance commands**:
  ```
  .venv/bin/python -m pytest tests/test_runner.py -q   # expected: new cases green, existing unaffected
  .venv/bin/python -m pytest -q                        # expected: all green (baseline 111 passed)
  grep -n "sensitive" src/AIQE/judge.py                # expected: matches the new branch line number
  ```
- **Timeout notice**: finish within 30 minutes; beyond 45 minutes stop and return partial results
  and blockers (including approaches already tried), and let the planner decide on downgrade
- **Deliverable format**: diff (str_replace format) + pasted acceptance-command output
```

## 4. Generic Testing Agent Skill

The bundled `skills/testing-agent/SKILL.md` is a **directly reusable agent instruction** (tools that support skill
directories, such as Claude Code, can load it directly): it hardens the testing discipline — red→green verification,
acceptance commands, no busywork disguised as self-verification, boundary declarations — into the Executor role's
actions before each job, rather than relying on agent self-discipline. How to integrate:

1. Copy the `skills/testing-agent/` directory into your project's `skills/` (or register the skill according to your
   tool's conventions);
2. When assigning Executor/Reviewer tasks, note in the task sheet "load skills/testing-agent/SKILL.md before starting
   work".

The full skill content is at [skills/testing-agent/SKILL.md](../skills/testing-agent/SKILL.md), and it is used together
with Sections 2 and 3 of this document: the task sheet defines "what to do", and the skill constrains "how to do it".
