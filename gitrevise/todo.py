import re
import sys
from enum import Enum
from typing import List, Set, Optional

from .odb import Commit, Oid, Repository
from .utils import run_editor, edit_commit_message, cut_commit


class StepKind(Enum):
    PICK = "pick"
    FIXUP = "fixup"
    SQUASH = "squash"
    REWORD = "reword"
    CUT = "cut"
    INDEX = "index"

    def __str__(self) -> str:
        return self.value

    @staticmethod
    def parse(instr: str) -> "StepKind":
        if "pick".startswith(instr):
            return StepKind.PICK
        if "fixup".startswith(instr):
            return StepKind.FIXUP
        if "squash".startswith(instr):
            return StepKind.SQUASH
        if "reword".startswith(instr):
            return StepKind.REWORD
        if "cut".startswith(instr):
            return StepKind.CUT
        if "index".startswith(instr):
            return StepKind.INDEX
        raise ValueError(
            f"step kind '{instr}' must be one of: pick, fixup, squash, reword, cut, or index"
        )


class Step:
    kind: StepKind
    commit: Commit

    def __init__(self, kind: StepKind, commit: Commit):
        self.kind = kind
        self.commit = commit

    @staticmethod
    def parse(repo: Repository, instr: str) -> "Step":
        parsed = re.match(r"(?P<command>\S+)\s(?P<hash>\S+)", instr)
        if not parsed:
            raise ValueError(
                f"todo entry '{instr}' must follow format <keyword> <sha> <optional message>"
            )
        kind = StepKind.parse(parsed.group("command"))
        commit = repo.get_commit(parsed.group("hash"))
        return Step(kind, commit)

    def __str__(self):
        return f"{self.kind} {self.commit.oid.short()} {self.commit.summary()}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Step):
            return False
        return self.kind == other.kind and self.commit == other.commit


def build_todos(commits: List[Commit], index: Optional[Commit]) -> List[Step]:
    steps = [Step(StepKind.PICK, commit) for commit in commits]
    if index:
        steps.append(Step(StepKind.INDEX, index))
    return steps


def autosquash_todos(todos: List[Step]) -> List[Step]:
    new_todos = todos[:]

    for step in reversed(todos):
        # Check if this is a fixup! or squash! commit, and ignore it otherwise.
        summary = step.commit.summary()
        if summary.startswith("fixup! "):
            kind = StepKind.FIXUP
        elif summary.startswith("squash! "):
            kind = StepKind.SQUASH
        else:
            continue

        # Locate a matching commit
        found = None
        needle = summary.split(maxsplit=1)[1]
        for idx, target in enumerate(new_todos):
            if target.commit.summary().startswith(needle):
                found = idx
                break

        if found is not None:
            # Insert a new `fixup` or `squash` step in the correct place.
            new_todos.insert(found + 1, Step(kind, step.commit))
            # Remove the existing step.
            new_todos.remove(step)

    return new_todos


def edit_todos(repo: Repository, todos: List[Step]) -> List[Step]:
    # Invoke the editors to parse commit messages.
    todos_text = "\n".join(str(step) for step in todos).encode()
    response = run_editor(
        repo,
        "git-revise-todo",
        todos_text,
        comments=f"""\
        Interactive Zipfix Todos ({len(todos)} commands)

        Commands:
         p, pick <commit> = use commit
         r, reword <commit> = use commit, but edit the commit message
         f, fixup <commit> = use commit, but fuse changes into previous commit
         s, squash <commit> = like fixup, but also edit the commit message
         c, cut <commit> = interactively split commit into two smaller commits
         i, index <commit> = leave commit changes unstaged

        These lines can be re-ordered; they are executed from top to bottom.

        If a line is removed, it will be treated like an 'index' line.

        However, if you remove everything, these changes will be aborted.
        """,
    )

    # Parse the response back into a list of steps
    result = []
    seen: Set[Oid] = set()
    seen_index = False
    for line in response.splitlines():
        if line.isspace():
            continue
        step = Step.parse(repo, line.decode(errors="replace").strip())
        result.append(step)

        # Produce diagnostics for duplicated commits.
        if step.commit.oid in seen:
            print(
                f"(warning) Commit {step.commit} referenced multiple times",
                file=sys.stderr,
            )
        seen.add(step.commit.oid)

        if step.kind == StepKind.INDEX:
            seen_index = True
        elif seen_index:
            raise ValueError("Non-index todo found after index todo")

    # Produce diagnostics for missing and/or added commits.
    before = set(s.commit.oid for s in todos)
    after = set(s.commit.oid for s in result)
    for oid in before - after:
        print(f"(warning) commit {oid} missing from todo list", file=sys.stderr)
    for oid in after - before:
        print(f"(warning) commit {oid} not in original todo list", file=sys.stderr)

    return result


def apply_todos(current: Commit, todos: List[Step], reauthor: bool = False) -> Commit:
    for step in todos:
        rebased = step.commit.rebase(current)
        if step.kind == StepKind.PICK:
            current = rebased
        elif step.kind == StepKind.FIXUP:
            current = current.update(tree=rebased.tree())
        elif step.kind == StepKind.REWORD:
            current = edit_commit_message(rebased)
        elif step.kind == StepKind.SQUASH:
            fused = current.message + b"\n\n" + rebased.message
            current = current.update(tree=rebased.tree(), message=fused)
            current = edit_commit_message(current)
        elif step.kind == StepKind.CUT:
            current = cut_commit(rebased)
        elif step.kind == StepKind.INDEX:
            break
        else:
            raise ValueError(f"Unknown StepKind value: {step.kind}")

        if reauthor:
            current = current.update(author=current.repo.default_author)

        print(f"{step.kind.value:6} {current.oid.short()}  {current.summary()}")

    return current
