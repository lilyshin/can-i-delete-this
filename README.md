# can-i-delete-this

A Claude Code skill that answers "can I delete this?" It traces why a line
exists past formatter noise, renames, code moves and squashed history to the
commit that actually introduced it, then grades the deletion risk with a
commit reference behind every grade above `unknown`.

![A dark-mode report: session_guard.py line 4 graded "Do not delete". The timeline shows the "chore: apply formatter" commit git blame reports rendered plain, and the real introduction tag on the 2018 security fix buried 111 commits earlier, found via pickaxe.](assets/hero.png)

## What `git blame` gets wrong

`blame` answers "who touched this line last," a different question from "why
does this line exist." From this project's own fixture (`build_f1`): a 2019
`hotfix: prevent double charge (#4127)` adds a duplicate-order guard, then a
2023 `chore: apply formatter` unifies quote style across 25 files, that line
included. `blame` on it today reports 2023, and the incident the guard exists
to prevent is invisible.

One qualification, because it is checkable in one command: `git blame -w`
already sees through a whitespace-only reformat, so whitespace noise is not
what this is for. What survives `-w` is token-level formatting (quote
unification, trailing commas, line splitting) plus renames, code moves,
squashes and reverts. That is the target.

## When you would reach for it

- **Reviewing a PR that deletes code.** Approving bets the removed guard was
  debris; blocking bets it was load-bearing. Neither bet has evidence yet.
- **Dead-code cleanup.** A function nothing seems to call, a flag whose
  consumers you cannot find. "Looks deletable" is the confidence level this
  replaces with a commit reference.
- **`blame` gave you a formatter.** You asked the right question and got
  `chore: apply formatter`. This is where the investigation usually dies.
- **Inherited code, authors gone.** "Why is this here" with nobody left to
  ask, so the history is the only witness still around.

## Install

    /plugin marketplace add lilyshin/can-i-delete-this
    /plugin install can-i-delete-this@can-i-delete-this

Codex, Copilot CLI and Gemini CLI read `~/.agents/skills/`; see `AGENTS.md`
for the symlink (this project does not duplicate the skill directory). No
install script ships here: a single-skill plugin has no state to migrate.

## Use it

Ask in your own words ("can I delete this", "why is this here", "who
introduced this and why"), or start from a target you already have:

    /can-i-delete-this:check src/payment.py:42
    /can-i-delete-this:check src/payment.py:10-25
    /can-i-delete-this:check chargeCustomerOnce

When no particular line is on your mind, scan instead:

    /can-i-delete-this:scan src/billing/

That looks for blocks of commented-out code and lists each with the commit
that commented it out, oldest first. It grades nothing: you pick an item,
and that item goes through the workflow above. The signal was picked by
measurement, and `skills/can-i-delete-this/batch-mode.md` has the numbers
and the boundaries.

`path:line` and `path:start-end` go straight to the tracer. A bare symbol is
looked up first, and the resolved file and line get stated back to you before
anything runs, so a wrong target cannot pass silently; with no argument it
asks instead of guessing. Both entry points run the same workflow.

Four steps, only one of which is the model's:

| Step | What it does |
|---|---|
| `trace.py` | Git facts: blame candidates scored for noise, introduction candidates via pickaxe and line history, revert chains, co-changed files, and disclosure of whatever the search truncated |
| the agent | Reads that JSON, recovers intent (tests, PR body, comments, in that order of trust over the commit subject), writes the verdict |
| `verdict.py` | Refuses a grade above `unknown` that carries no commit reference. Enforced, not documented |
| `render.py`, `artifacts.py` | A self-contained HTML report (no CDN, no external font, light and dark), plus paste-ready next-step text |

Facts come only from git: the agent says *which* commit, git says *what that
commit is*. Nothing else in the pipeline is allowed to invent a sha, a
subject or a date.

## What comes back

| Grade | Meaning | Artifact you get |
|---|---|---|
| `danger` | A hotfix, an incident, a revert chain, or a test guards it | Keep-comment for the code |
| `conditional` | The reason was time-bound (a version, a platform, a migration) | Checklist of conditions to verify first |
| `safe` | The reason demonstrably no longer applies | PR body for the deletion |
| `unknown` | No evidence found, which is a valid answer | The question to ask, and who to ask |

A `danger` verdict with no guarding test says so and proposes the regression
test to add before anything gets deleted.

Those four artifacts are also how a verdict outlives the report. A
keep-comment lives in the code, where the next person to consider deleting
the line will see it without knowing this tool exists. A pull request body
lives in the git history of the deletion, which is where "we checked, and
it was safe" belongs once the code is gone. An unknown verdict becomes a
question addressed to a named author. There is no cache and no database on
purpose: a stored verdict goes stale silently, while a comment travels with
the line it describes and gets read in review.

<details>
<summary>Reproduce the report at the top of this page</summary>

The hero image is a render against a fixture, not a mockup:

    python3 -c "
    import sys; sys.path.insert(0, 'tests/fixtures')
    from make_fixture_repo import build_deep_history
    print(build_deep_history('/tmp/cidt-demo'))"
    python3 skills/can-i-delete-this/scripts/trace.py \
      --repo /tmp/cidt-demo/deep_history --file session_guard.py --lines 4:4

113 commits on one file. Line 4 is a security guard added by
`fix: reject replayed session tokens after logout (#5521)` in January 2018,
buried under 110 build-marker commits, then re-touched by a formatter that
flipped its quote style. `blame` reports the formatter (`why: "blame"` in the
output); the 2018 fix comes back via `why: "pickaxe"`. The verdict cites the
fix as `role: "introduced"` and the formatter as `role: "reference"`, which
is why exactly one row in the hero carries the real-introduction tag.

</details>

## When you do not need it

Check the history size first, and use `--follow` (without it, a renamed file
comes back undercounted, which is the one case where tracing earns its keep):

    git log --oneline --follow -- <path> | wc -l

Twenty commits or fewer: read it yourself with `git log -p --follow`. We
measured this instead of assuming it, and an agent with no skill loaded beat
ranked output on a three-commit fixture. Past that, `log -p` stops fitting in
one read and the tracer's ranked candidates earn their place: against a
113-commit fixture under time pressure, unaided runs failed two of three (one
answered in 8.5 seconds having read no history and did not say so, another
answered confidently about the wrong line and recommended deleting it), while
six of six skill-loaded runs found the real introducing commit.

The full record, caveats and failures included (among them one rule this
scenario never genuinely tested), is in
[CREATION-LOG.md](skills/can-i-delete-this/CREATION-LOG.md) and
[tests/pressure/](tests/pressure/).

## Seven blame traps, each a buildable fixture

Every row is a real git repository, not a description. Build one with
`tests/fixtures/make_fixture_repo.py` and check the behavior yourself.

| Case | Why plain `blame` gets it wrong | Fixture |
|---|---|---|
| Token-level formatter sweep | Survives `blame -w` because it changes tokens, not whitespace | `build_f1` |
| Rename bundled with unrelated edits | Bundling drops similarity below blame's copy-detection threshold | `build_f2` |
| Cross-file move, origin left behind | `blame -C -C -C` is documented to follow this but empirically does not when the origin is not removed | `build_f3` |
| Squashed history | No earlier commit exists to recover, and a PR-title-shaped subject cannot be trusted for intent | `build_f4` |
| Revert, then reintroduced | `blame` reports the reapply, never the original or the revert between | `build_f5` |
| Vendored dump with a coincidental match | A pickaxe search on that token alone would implicate the vendor commit | `build_f6` |
| Merge commit holding a hand-resolved conflict | The combined line matches neither parent, so blame credits the merge | `build_f7` |

Each row's test is named in
[noise-catalog.md](skills/can-i-delete-this/noise-catalog.md), which
documents eleven noise categories (N1-N11) in total.

## No language assumptions, and no commit-convention assumptions

A commit is filtered out of the candidate list on **what it changed**: the
diff, the file paths, the commit graph. Never on how its author described it.
So a formatter sweep is caught whether its subject reads
`chore: apply formatter`, `잡일: 포맷터 일괄 적용`, `フォーマッタを適用`,
`cleanup`, or nothing recognizable at all
(`tests/test_noise_language_independence.py` builds the same repository six
ways and pins one verdict across all of them).

Filtering on the subject would fail twice over. It would score non-English
repositories as if every sweep were a real change, and in English it would
delete evidence: on a 20,000-commit repository, the commit `blame` reports for
one line touches 310 files with a PR-shaped subject, while its diff on that
one file removes 6 lines and adds 18. It wrote the line being asked about.

Subject vocabulary is still read, and reported as `hints` for the agent to
weigh alongside the diff, because the model in this pipeline reads every
language and a regex reads one. Leaving debris in the candidate list costs one
extra read; discarding the real introducing commit cannot be undone.

## Safety

- **Read-only.** `gitq.py` allows sixteen read subcommands and nothing else.
  There is no write path to a git object, a working-tree file, or the index
  anywhere in this project.
- **Sanitized environment, not just a flag denylist.** Every invocation
  forces `-c core.pager=cat` and `-c diff.external=` and overrides the
  pager, external-diff, editor and askpass variables, so a repo's own config
  cannot name a program to exec even through a flag this project has not
  thought of. `CONTRIBUTING.md` has the full reasoning, including the `-O`
  hole that prompted it.
- **Never writes to your files.** No comment injected, no PR opened, no file
  edited. Scripts print text; `--copy` puts it on your clipboard only
  because you asked.
- **No network, no third-party dependency.** Standard library, Python 3.9+.

## License

MIT. See `LICENSE`. Contributions welcome, in Korean or English:
`CONTRIBUTING.md`.

<details>
<summary>🇰🇷 한국어로 읽기</summary>

`git blame`은 "누가 마지막으로 이 줄을 건드렸나"를 답하는데, 정작 필요한
질문은 "이 줄이 왜 존재하나"입니다. 포맷터 일괄 적용, rename, 코드 이동,
squash가 실제 도입 커밋 위에 쌓이면 blame은 맨 위에 있는 것만 보여줍니다.
이 스킬은 blame 후보를 노이즈로 채점하고 pickaxe와 line-history로 실제 도입
커밋을 찾아, 삭제 위험도를 커밋 근거와 함께 등급으로 매깁니다
(`danger`/`conditional`/`safe`/`unknown`). 등급마다 바로 쓸 수 있는 결과물이
따라옵니다(KEEP 코멘트, 삭제 전 확인 체크리스트, PR 본문, 물어볼 질문).

**쓰이는 순간 네 가지:** 코드를 지우는 PR을 리뷰할 때, dead code를 정리하다
"지워도 될 것 같은데"에서 멈출 때, `git blame`이 `chore: apply formatter`를
답으로 내놓아 조사가 끝나버릴 때, 원작자가 떠난 코드에서 물어볼 사람이
히스토리밖에 없을 때.

**측정으로 좁힌 경계 두 가지.** `git blame -w`는 공백만 바뀐 포맷터를 이미
스스로 뚫으므로, 이 도구가 겨냥하는 것은 quote 통일 같은 **토큰을 바꾸는**
포맷터와 rename·코드 이동·squash·revert입니다. 그리고 커밋 20개 이하인
파일은 `git log -p --follow`로 직접 읽는 게 낫습니다(스킬 없는 에이전트가
커밋 3개짜리 fixture에서 정답을 냈습니다). 113커밋 히스토리를 시간 압박
속에서 조사시키면 스킬 없이는 3번 중 2번 실패했고(한 번은 8.5초 만에
히스토리를 안 보고 답하며 그 사실을 숨겼고, 한 번은 물어본 줄이 아닌 다른
줄에 삭제를 권했습니다), 스킬 적용 후에는 6번 모두 실제 도입 커밋을
찾았습니다. 실패와 단서를 포함한 전체 기록은
`skills/can-i-delete-this/CREATION-LOG.md`와 `tests/pressure/`에 있습니다.

**알려진 한계:** `noise.py`의 키워드 채점은 영어 커밋 메시지만 인식합니다.
한국어 제목의 포맷터 sweep은 파일이 아무리 많아도 노이즈로 잡히지 않습니다.
반면 구조적 신호(whitespace-only, vendored·생성 경로, merge, import 비율)와
pickaxe·line-history는 커밋 메시지를 읽지 않으므로 언어와 무관합니다.

설치는 `/plugin marketplace add lilyshin/can-i-delete-this`. 사용자 파일에
쓰지 않고, 네트워크를 쓰지 않고, 표준 라이브러리 외 의존성이 없습니다.
이슈·PR·커밋 메시지는 한국어로 쓰셔도 됩니다.

</details>
