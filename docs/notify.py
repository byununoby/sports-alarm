"""텔레그램 알림 (선택 기능).

docs/data/games.json 을 읽어 다음 내용을 한 메시지로 보낸다.
  - 오늘 경기 (홈/원정, 시간, 장소)
  - 오늘 / 내일 티켓 오픈 예정 홈경기 + 예매 링크

환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 가 없으면 아무것도 안 하고 끝난다.
보낼 내용이 없으면 메시지를 보내지 않는다 (--always 로 강제 전송).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
WD = "월화수목금토일"


def label(g: dict, team_names: dict) -> str:
    home_id, away_id = g["home"]["team_id"], g["away"]["team_id"]
    mine = team_names.get(home_id) or team_names.get(away_id)
    side = "홈" if home_id else "원정"
    sport = "축구" if g["sport"] == "football" else "농구"
    return f"[{sport}] {mine} {side} | {g['home']['name']} vs {g['away']['name']}"


def build_message(data: dict, now: datetime) -> str | None:
    team_names = {t["id"]: t["name"] for t in data["teams"]}
    today = now.date()
    tomorrow = today + timedelta(days=1)
    games = data["games"]

    today_games = [g for g in games if g["date"] == today.isoformat() and g["status"] == "예정"]
    opens_today, opens_tomorrow = [], []
    for g in games:
        t = g.get("ticket")
        if not t or g["status"] != "예정":
            continue
        op = datetime.fromisoformat(t["open_at"])
        if op.date() == today and op > now - timedelta(hours=1):
            opens_today.append((op, g))
        elif op.date() == tomorrow:
            opens_tomorrow.append((op, g))

    if not (today_games or opens_today or opens_tomorrow):
        return None

    out = [f"<b>직관 알림 {today.month}/{today.day}({WD[today.weekday()]})</b>"]
    if today_games:
        out.append("\n<b>오늘 경기</b>")
        for g in today_games:
            out.append(f"{g['time'] or '시간미정'}  {label(g, team_names)}\n  {g['venue'] or ''}"
                       + (f" / 중계 {', '.join(g['broadcast'])}" if g["broadcast"] else ""))
    for title, items in (("오늘 티켓 오픈", opens_today), ("내일 티켓 오픈", opens_tomorrow)):
        if items:
            out.append(f"\n<b>{title}</b>")
            for op, g in sorted(items, key=lambda x: x[0]):
                gd = datetime.fromisoformat(g["date"])
                tag = "예상" if g["ticket"].get("estimated", True) else "확정"
                out.append(f"{op:%H:%M} 오픈({tag})  {label(g, team_names)} ({gd.month}/{gd.day} {g['time'] or ''})\n"
                           f"  <a href=\"{g['ticket']['url']}\">예매 페이지 열기</a>")
    return "\n".join(out)


def send(token: str, chat_id: str, text: str) -> None:
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    with urllib.request.urlopen(req, timeout=20) as res:
        res.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--always", action="store_true", help="보낼 내용이 없어도 전송")
    ap.add_argument("--dry-run", action="store_true", help="전송하지 않고 출력만")
    ap.add_argument("--now", help="(테스트용) 기준 시각 ISO")
    args = ap.parse_args()

    data = json.loads((ROOT / "docs" / "data" / "games.json").read_text(encoding="utf-8"))
    now = datetime.fromisoformat(args.now).replace(tzinfo=KST) if args.now else datetime.now(KST)
    msg = build_message(data, now)
    if msg is None:
        if not args.always:
            print("오늘 알릴 내용 없음")
            return 0
        msg = "오늘은 경기도, 티켓 오픈도 없습니다."

    if args.dry_run:
        print(msg)
        return 0
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정: 텔레그램 전송 생략")
        return 0
    send(token, chat_id, msg)
    print("텔레그램 전송 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
