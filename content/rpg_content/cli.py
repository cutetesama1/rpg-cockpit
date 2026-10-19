"""内容包命令行工具：`python -m rpg_content.cli <new|lint|validate>`。

因为 `rpg_content` 需要 `content/` 在 sys.path 上，仓库里推荐用包装脚本：

    python tools/pack.py new packs/my-pack --id my-pack --title "我的包"
    python tools/pack.py lint packs/night-convenience-store --strict
    python tools/pack.py validate packs/night-convenience-store
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rpg_content.lint import LintIssue, lint_pack_dir
from rpg_content.pack import PackError, load_pack
from rpg_content.scaffold import TEMPLATES, scaffold_pack


def _print_issues(issues: list[LintIssue]) -> None:
    for issue in issues:
        print(issue.format())


def _summarize(issues: list[LintIssue]) -> tuple[int, int]:
    errors = sum(1 for i in issues if i.level == "error")
    warnings = sum(1 for i in issues if i.level == "warning")
    return errors, warnings


def cmd_new(args: argparse.Namespace) -> int:
    try:
        written = scaffold_pack(
            args.path,
            pack_id=args.id,
            title=args.title,
            template=args.template,
            force=args.force,
        )
    except (ValueError, FileExistsError) as exc:
        print(f"无法创建内容包：{exc}", file=sys.stderr)
        return 2
    print(f"已创建内容包 {args.path}（{len(written)} 个文件）")
    for path in written:
        print(f"  {path}")
    print("\n下一步：编辑 prompts/settler.md 与 scenes/opening.json，然后运行")
    print(f"  python tools/pack.py lint {args.path} --strict")
    return 0


def cmd_lint(args: argparse.Namespace) -> int:
    issues = lint_pack_dir(args.path)
    errors, warnings = _summarize(issues)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "level": i.level,
                        "code": i.code,
                        "path": i.path,
                        "message": i.message,
                    }
                    for i in issues
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_issues(issues)
        print(f"\n{errors} error / {warnings} warning")
    if errors or (args.strict and warnings):
        return 1
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        pack = load_pack(args.path, lint_warnings=args.strict)
    except PackError as exc:
        print(f"内容包不可用：{exc}", file=sys.stderr)
        return 1
    print(
        f"内容包可用：{pack.manifest.id} v{pack.manifest.version} "
        f"（{len(pack.state.fields)} 字段 / {len(pack.skills)} 技能 / "
        f"{len(pack.scenes) or 1} 场景 / prompts {sorted(pack.prompts)}）"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rpg-pack", description="RPG Framework 内容包工具")
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="生成一个能通过 lint 的最小内容包")
    new.add_argument("path", type=Path)
    new.add_argument("--id", required=True, help="包 id（小写字母/数字/连字符）")
    new.add_argument("--title", required=True, help="包标题")
    new.add_argument("--template", default="minimal", choices=TEMPLATES)
    new.add_argument("--force", action="store_true", help="目标目录非空时覆盖")
    new.set_defaults(func=cmd_new)

    lint = sub.add_parser("lint", help="列出全部内容包问题（error + warning）")
    lint.add_argument("path", type=Path)
    lint.add_argument("--strict", action="store_true", help="warning 也返回非零退出码")
    lint.add_argument("--json", action="store_true", help="输出 JSON，供编辑器集成")
    lint.set_defaults(func=cmd_lint)

    validate = sub.add_parser("validate", help="只检查能否加载（CI 用）")
    validate.add_argument("path", type=Path)
    validate.add_argument("--strict", action="store_true", help="warning 也视为失败")
    validate.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
