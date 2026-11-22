"""命令行入口：

  python3 -m cabin_review run --data data --out out [--as-of YYYY-MM-DD]
  python3 -m cabin_review diff 旧状态.json 新状态.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model import Data
from .report import render
from .state import build_state, diff_states


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cabin_review")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="做一次漏标审查并输出报告与状态")
    run.add_argument("--data", default="data", help="资料目录")
    run.add_argument("--out", default="out", help="输出目录")
    run.add_argument("--as-of", default=None,
                     help="只采用该日期及之前可见的裁定(YYYY-MM-DD)")

    diff = sub.add_parser("diff", help="比较两次审查状态")
    diff.add_argument("old", help="旧状态 JSON")
    diff.add_argument("new", help="新状态 JSON")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        data = Data(args.data)
        state = build_state(data, as_of=args.as_of)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "report.md").write_text(render(state), encoding="utf-8")
        print(f"已写出 {out/'report.md'} 与 {out/'state.json'}")
        return 0
    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    result = diff_states(old, new)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
