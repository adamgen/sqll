# Rules and fixes

Status: frozen (Core track, task C12). Package: `sqll_lint`. Interface
test: `crates/sqll_interfaces/tests/rules.rs`. Design:
[s3b-core.md](../decisions/s3b-core.md), Q4. The rules of S5 implement this
interface in `sqll_rules`. Change to the C4 design (Q4): a fix has the
sqlfluff edit types of an anchor node and gives one edit, and the rule
function is `eval` for each node of the crawl, with a `Result`.

## The interface

- `Rule`: `code`, `name`, `description`, `groups`, `aliases`,
  `config_keywords`, `lint_phase` (`Main` or `Post`), `is_fix_compatible`,
  `targets_templated`, `crawl_behaviour`, `check_config` (fail closed
  before a lint), and `eval(&mut RuleContext) -> Result<Vec<LintResult>,
  LintError>`. An `Err` stops the lint: sqlfluff gives an "Unexpected
  exception" violation and stops the rule; sqll fails closed.
- The metadata of a rule must be that of the sqlfluff rule with the same
  code (`RULES`, `src/sqlfluff.rs`). `Registry::new` refuses another code
  or other metadata.
- `CrawlBehaviour`: `RootOnly` or `SegmentSeeker { types, allow_recurse,
  works_on_unparsable }` (the sqlfluff crawlers). `crawl(tree)` gives the
  nodes in pre-order; it does not go into an `unparsable` node, unless
  `works_on_unparsable`.
- `RuleContext`: `segment` (a `NodeRef` of the typed view,
  [typed-view.md](typed-view.md)), `dialect`, `config` (`RuleConfig`: the
  keyword values of the rule, and `core`), `memory` (`Memory`: the state of
  one crawl, empty at its start), `parent`, `parent_stack`, and `tree`.
- `LintResult`: `anchor` (a node), `description` (`None` gives the rule
  description), and `fixes`.
- `Fix`: `Replace`, `CreateBefore`, `CreateAfter` (each with a text), and
  `Delete`, of an anchor node. `edit(tree)` gives the edit of the templated
  text; `source_edit(tree)` gives the `SourceEdit` (a source byte range and
  a text) through the source map ([source-map.md](source-map.md)).
- `Registry` and `RulePack`: `select(config)` gives the selected rules in
  code order, with their `RuleConfig`, as the sqlfluff `get_rulepack`:
  `rules` and `exclude_rules` with codes, names, groups, aliases, and
  `fnmatch` globs; the sqlfluff validation of the rule config values.
- `Linter { pack, settings, dialect }` and `lint(source, parser, fix)`:
  the sqlfluff `lint_fix_parsed`. `SourceParser` templates and parses a
  source text; `TemplaterParser` does it with a `Templater` and
  `sqll_syntax::parse` ([parse.md](parse.md)). The result `LintedFile`
  has `fixed` (the source after the fixes), `violations` (`Violation`:
  code, name, description, source range, start and end line and position,
  source edits, literal flag), `parse_errors`, and `warnings`.
- `LintSettings::from_config`: `runaway_limit`, `ignore_templated_areas`,
  and the `noqa` settings.

## Fixes and the source map

A fix must not change the output of a template tag:

- An anchor is literal if its source range (the sqlfluff source slice of the
  node) is literal and is its templated text.
- `Replace` and `Delete` change the source range of a literal anchor. Else
  the fix is refused (`FixRefusal::Templated`).
- `CreateBefore` and `CreateAfter` of a literal anchor go to the start or
  the end of its source range. Of another anchor, the text goes before the
  source of the next character if it is literal, else after the source of
  the character before it if that is literal. Else the fix is refused.
- The fixes of one result must not touch two template blocks
  (`MultipleBlocks`, sqlfluff issue 3079).

A refused fix makes its result not fixable, as the sqlfluff
`discard_unsafe_fixes`.

## The fix loop

As sqlfluff: a lint runs one loop. A fix runs the main phase up to
`runaway_limit` loops, then the post phase up to 2 loops. The first loop runs each rule. After each rule with fixes,
the loop checks the anchors (one fix for each anchor, or one
`CreateBefore` and one `CreateAfter`), applies the source edits, and
parses the fixed source again. It stops when a loop changes nothing. At the
limit, the result is the input source and no violation is fixable. The
violations are those of the first loop; then `ignore_templated_areas`
removes those in templated sections, and the list is sorted with no
duplicate.

## Fail closed

`unsupported` and exit code 2: a selected rule that sqll does not have (the
default `rules = all` selects 79), a `noqa` comment (sqll does not read
them yet, S5), `fix_even_unparsable = True`, a rule setting that the rule
cannot do (CP01, CP03, CP04: `ignore_words_regex`), a rule error, and an
unsupported templater setting.

## Differences from sqlfluff

- sqlfluff changes the tree; sqll changes the source and parses it again.
  A fixed source is applied only if its parse has a tree and no more parse
  errors than before; sqlfluff checks only the changed segment.
- sqlfluff refuses a fix only if it touches a `templated` raw slice; sqll
  also refuses a change of a block tag or a comment slice. sqll has no
  source-only fix (`LintFix.source`, JJ01 is S11).
- Overlapping source edits of one rule: no fix of that rule applies.
- Not yet: the placeholder rule of `remove_templated_errors` (S6), the
  `ignore` and `warnings` settings (C13), and `noqa` (S5).
- CP01, CP03, CP04: a target with children changes the memory as in
  sqlfluff; if it needs a fix, sqlfluff raises an exception and sqll fails
  closed. A node with one target leaf child of the same text is not
  examined; the child is (the sqll parser makes some sqlfluff raw segments
  so, for example the sparksql `DIV`).

## Proof (C12)

- `scripts/s3b/rules_oracle.py` records the sqlfluff data in
  `results/S3b/C12-rules.json` (`check` in the CI job build): the manifest
  of the 79 rules, the 37 validated config keywords, and the rule test
  helper answers of the 51 cases of `CP01.yml`, `CP03.yml`, `CP04.yml`.
  `src/sqlfluff.rs` is its table.
- `crates/sqll_rules/tests/fixtures.rs` runs the cases from the submodule
  as `rules__test_helper`, and also compares each violation (code, lines,
  positions, description, fixable) and fixed text with the record:

  | Cases | Passed | Failed | Unsupported | Not run |
  |---|---|---|---|---|
  | Raw templater, default config | 13 | 0 | 0 | 0 |
  | Raw templater, a config | 25 | 0 | 7 (`ignore_words_regex`) | 0 |
  | Jinja (S11) | 0 | 0 | 0 | 6 |

- The interface test: a test templater gives the C8 hand-built map of
  `jinja_a`; a test rule fixes the literal keywords of it through the fix
  loop, and keeps the template tags; a fix of the output of a tag is
  refused. Also the registry, the selection, the validation, the fix loop
  cases, and the crawl.

## Rules for a change

- A change of a signature fails the interface test (`signatures`). Change
  the test and this document in the same Core pull request.
- A new rule (S5) implements `Rule` in `sqll_rules` with the sqlfluff
  metadata, and adds it to `sqll_rules::rules`. It must not change
  `sqll_lint`.
