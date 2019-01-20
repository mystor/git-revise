import re
from enum import Enum
from typing import List, Set, Optional

from .odb import Commit, Oid, Repository
from .utils import run_editor, edit_commit_message


class StepKind(Enum):
    PICK = "pick"
    FIXUP = "fixup"
    REWORD = "reword"
    INDEX = "index"

    def __str__(self) -> str:
        return self.value

    @staticmethod
    def parse(instr: str) -> "StepKind":
        if "pick".startswith(instr):
            return StepKind.PICK
        if "fixup".startswith(instr):
            return StepKind.FIXUP
        if "reword".startswith(instr):
            return StepKind.REWORD
        if "index".startswith(instr):
            return StepKind.INDEX
        raise ValueError(
            f"step kind '{instr}' must be one of: pick, fixup, reword, or index"
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


def edit_todos(repo: Repository, todos: List[Step]) -> List[Step]:
    # Invoke the editors to parse commit messages.
    todos_text = "\n".join(str(step) for step in todos).encode()
    response = run_editor(
        "git-zipfix-todo",
        todos_text,
        comments=f"""\
        Interactive Zipfix Todos ({len(todos)} commands)

        Commands:
         p, pick <commit> = use commit
         r, reword <commit> = use commit, but edit the commit message
         f, fixup <commit> = use commit, but fuse changes into previous commit
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
            print(f"(warning) Commit {step.commit} referenced multiple times")
        seen.add(step.commit.oid)

        if step.kind == StepKind.INDEX:
            seen_index = True
        elif seen_index:
            raise ValueError("Non-index todo found after index todo")

    # Produce diagnostics for missing and/or added commits.
    before = set(s.commit.oid for s in todos)
    after = set(s.commit.oid for s in result)
    for oid in before - after:
        print(f"(warning) commit {oid} missing from todo list")
    for oid in after - before:
        print(f"(warning) commit {oid} not in original todo list")

    return result


def apply_todos(current: Commit, todos: List[Step], reauthor: bool = False) -> Commit:
    for step in todos:
        rebased = step.commit.rebase(current)
        if step.kind == StepKind.PICK:
            current = rebased
        elif step.kind == StepKind.FIXUP:
            current = current.update(tree=rebased.tree())
        elif step.kind == StepKind.REWORD:
            current = edit_commit_message(current)
        elif step.kind == StepKind.INDEX:
            break
        else:
            raise ValueError(f"Unknown StepKind value: {step.kind}")

        if reauthor:
            current = current.update(author=current.repo.default_author)

        print(f"{current.oid.short()} {current.summary()}")

    return current
