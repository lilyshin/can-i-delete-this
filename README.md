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

That finds blocks of commented-out code, line comments and `/* */` alike,
and lists each one with the first lines of its own text and the commit that
commented it out, oldest first:

    - [ ] **look first** `billing.py:2-6` (5 lines, commented out 1891 days ago)
          | if order.retryable:
          | for attempt in range(3):
          `d624b5f` hotfix: disable retry during gateway outage
          > Gateway keeps returning 502. Restore after #3391.

It grades nothing. You pick an item, and that item goes through the
workflow above.

The excerpt lines exist because a commit line is often not enough to tell
candidates apart. In one real scan, forty of forty-three candidates traced
to the same 142-file merge, so their commit lines were identical and only
each block's own text distinguished them. Those lines are real code lifted
out of the repository, and the checklist says so in its own footer, since
the person pasting it into an issue is the one who needs to know.

Both signals were picked by measurement rather than taste, and
`skills/can-i-delete-this/batch-mode.md` has the numbers and the
boundaries, including what the scan deliberately does not detect.

`path:line` and `path:start-end` go straight to the tracer. A bare symbol is
looked up first, and the resolved file and line get stated back to you before
anything runs, so a wrong target cannot pass silently; with no argument it
asks instead of guessing. Both entry points run the same workflow.

Five steps, only one of which is the model's:

| Step | What it does |
|---|---|
| `trace.py` | Git facts: blame candidates scored for noise, introduction candidates via pickaxe and line history, revert chains, co-changed files, and disclosure of whatever the search truncated |
| the agent | Reads that JSON, recovers intent (tests, PR body, comments, in that order of trust over the commit subject), writes the verdict |
| `verdict.py` | Refuses a grade above `unknown` that carries no commit reference. Enforced, not documented |
| `render.py`, `artifacts.py` | A self-contained HTML report (no CDN, no external font, light and dark), plus paste-ready next-step text |
| `patch.py` | Turns a `danger` verdict's keep-comment into a unified diff for `git apply`; refuses when the target moved since the trace ran, or when the keep-comment carries no resolved citation |

Facts come only from git: the agent says *which* commit, git says *what that
commit is*. Nothing else in the pipeline is allowed to invent a sha, a
subject or a date.

What stays the same across releases, and what does not, is in
[docs/stability.md](docs/stability.md).

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

A `danger` keep-comment does not have to be pasted in by hand: `patch.py`
turns the same comment into a unified diff you apply yourself with
`git apply`. The tool only produces that diff; it does not touch the target
file and does not run `git apply` on your behalf.

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

- **Read-only against git.** `gitq.py` allows sixteen read subcommands and
  nothing else. No git object and no index entry is ever written.
- **Sanitized environment, not just a flag denylist.** Every invocation
  forces `-c core.pager=cat` and `-c diff.external=` and overrides the
  pager, external-diff, editor and askpass variables, so a repo's own config
  cannot name a program to exec even through a flag this project has not
  thought of. `CONTRIBUTING.md` has the full reasoning, including the `-O`
  hole that prompted it.
- **Never edits your code.** No comment injected, no PR opened, no file of
  yours edited. Two scripts do write a file, and neither is source:
  `render.py` writes the HTML report, to your system temp directory unless
  you point `--outdir` somewhere, and `patch.py --out` writes the patch file
  at the path you named, refusing when that path is the file under
  investigation. Applying the patch is your `git apply`, never ours.
  Everything else is printed, and `--copy` reaches your clipboard because
  you asked.
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
`danger` 등급의 KEEP 코멘트는 손으로 붙여넣는 대신, `patch.py`로 만든 패치
파일을 `git apply`로 적용할 수도 있습니다. 도구는 패치만 만들 뿐, 대상
파일에 직접 쓰거나 `git apply`를 대신 실행하지는 않습니다.

무엇이 릴리스마다 그대로 유지되고 무엇이 아닌지는
[docs/stability.md](docs/stability.md)에 있습니다.

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

**커밋 메시지 언어와 컨벤션에 의존하지 않습니다.** 후보를 목록에서 빼는
판단은 커밋이 **무엇을 바꿨는지**(diff·경로·커밋 그래프)로만 하고, 저자가
그것을 어떻게 서술했는지로는 하지 않습니다. 그래서 포맷터 sweep은 제목이
`chore: apply formatter`든 `잡일: 포맷터 일괄 적용`이든 `フォーマッタを適用`이든
`cleanup`이든 알아볼 수 없는 무엇이든 똑같이 잡힙니다. 제목 어휘는 읽되
`hints`로 에이전트에게 넘겨 판단 재료로만 씁니다. 제목으로 필터링하면 영어
외 언어에서 무력해지는 동시에 영어에서는 근거를 삭제합니다. 2만 커밋
저장소에서 blame이 지목한 커밋이 310파일 PR 형태라 옛 규칙이 버렸는데, 그
커밋의 대상 파일 diff는 -6/+18로 물어본 그 줄을 실제로 쓴 커밋이었습니다.

**의심할 대상이 딱히 없을 때는 스캔합니다.**

    /can-i-delete-this:scan src/billing/

주석 처리된 코드 블록을 찾아(줄 주석과 `/* */` 모두), 블록의 첫 줄들과
주석 처리한 커밋을 함께 오래된 순으로 나열합니다. **등급은 매기지 않습니다.**
목록에서 하나를 고르면 그 항목이 위 워크플로를 탑니다. 발췌를 넣은 이유는
커밋 정보만으로는 후보가 구분되지 않기 때문입니다. 실제 스캔에서 후보 43건
중 40건이 같은 142파일 머지 커밋에 걸려 커밋 줄이 전부 동일했고, 각 블록의
텍스트만이 그것들을 갈랐습니다. 발췌는 저장소의 실제 코드라서 체크리스트를
이슈에 붙이면 그 코드도 함께 갑니다. 그 사실을 체크리스트 자체가 밝힙니다.

설치는 `/plugin marketplace add lilyshin/can-i-delete-this`. 사용자 코드는
고치지 않습니다. 파일을 쓰는 곳은 두 군데뿐이고 둘 다 소스가 아닙니다.
`render.py`가 HTML 리포트를 쓰고(기본 위치는 시스템 임시 디렉토리, `--outdir`로
바꿀 수 있습니다), `patch.py --out`이 지정한 경로에 패치를 씁니다(그 경로가
조사 대상 파일이면 거절합니다). 패치 적용은 사용자의 `git apply`입니다.
네트워크를 쓰지 않고, 표준 라이브러리 외 의존성이 없습니다.
이슈·PR·커밋 메시지는 한국어로 쓰셔도 됩니다.

</details>
