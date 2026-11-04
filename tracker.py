"""K리그 / KBL 관심팀 일정 수집기.

실행하면 다음 파일을 만든다.
  docs/data/games.json        대시보드(웹페이지)가 읽는 데이터
  docs/calendar/all.ics       전체 팀 캘린더 (경기 + 티켓오픈 일정, 알람 포함)
  docs/calendar/<팀id>.ics    팀별 캘린더

외부 라이브러리 없이 파이썬 3.9+ 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
KST = ZoneInfo("Asia/Seoul")
UA = "Mozilla/5.0 (sports-alarm; personal schedule tracker)"

KLEAGUE_URL = "https://www.kleague.com/getScheduleList.do"
KBL_URL = "https://api.kbl.or.kr/match/list"

GAME_MINUTES = {"football": 120, "basketball": 135}


# ---------------------------------------------------------------- 수집

def http_json(url: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json, text/plain, */*")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode("utf-8"))


def months_between(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def fetch_kleague(start: date, end: date) -> list[dict]:
    rows: dict[tuple, dict] = {}
    for y, m in months_between(start, end):
        for league in (1, 2):
            try:
                payload = http_json(
                    KLEAGUE_URL, method="POST",
                    body={"year": str(y), "month": f"{m:02d}", "leagueId": league},
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            except Exception as e:  # 한 달 실패해도 나머지는 계속
                print(f"[경고] K리그{league} {y}-{m:02d} 조회 실패: {e}", file=sys.stderr)
                continue
            data = payload.get("data", payload) or {}
            for it in data.get("scheduleList") or []:
                key = (it.get("year"), it.get("leagueId"), it.get("meetSeq"), it.get("gameId"))
                rows[key] = it
    return list(rows.values())


def fetch_kbl(start: date, end: date) -> list[dict]:
    rows: dict[str, dict] = {}
    for y, m in months_between(start, end):
        first = date(y, m, 1)
        last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
        q = urllib.parse.urlencode({
            "fromDate": first.strftime("%Y%m%d"),
            "toDate": last.strftime("%Y%m%d"),
            "tcodeList": "all",
        })
        try:
            payload = http_json(
                f"{KBL_URL}?{q}",
                headers={"channel": "WEB", "teamcode": "XX", "lang": "ko",
                         "X-Requested-With": "XMLHttpRequest"},
            )
        except Exception as e:
            print(f"[경고] KBL {y}-{m:02d} 조회 실패: {e}", file=sys.stderr)
            continue
        for it in payload if isinstance(payload, list) else []:
            rows[it.get("gmkey") or json.dumps(it, sort_keys=True)] = it
    return list(rows.values())


# ---------------------------------------------------------------- 정규화

def kleague_team_match(team: dict, code: str | None, name: str | None) -> bool:
    if code and team.get("kleague_code") == code:
        return True
    return bool(name) and name.replace(" ", "") in {n.replace(" ", "") for n in team.get("names", [])} \
        and not code  # 코드가 있으면 코드로만 판정 (수원FC/수원삼성 혼동 방지)


def normalize_kleague(it: dict, teams: list[dict]) -> dict | None:
    football = [t for t in teams if t["sport"] == "football"]
    home_t = next((t for t in football if kleague_team_match(t, it.get("homeTeam"), it.get("homeTeamName"))), None)
    away_t = next((t for t in football if kleague_team_match(t, it.get("awayTeam"), it.get("awayTeamName"))), None)
    if not home_t and not away_t:
        return None
    d = (it.get("gameDate") or "").replace(".", "-")
    t = it.get("gameTime") or ""
    league_name = f"K리그{it.get('leagueId')}"
    match_url = None
    if it.get("gameId") and it.get("meetSeq"):
        match_url = (f"https://www.kleague.com/match.do?year={it.get('year')}&leagueId={it.get('leagueId')}"
                     f"&gameId={it.get('gameId')}&meetSeq={it.get('meetSeq')}")
    status = {"FE": "종료", "NS": "예정", "PP": "연기", "CAN": "취소"}.get(
        it.get("gameStatus") or "", "종료" if it.get("endYn") == "Y" else "예정")
    return {
        "id": f"kl-{it.get('year')}-{it.get('leagueId')}-{it.get('meetSeq')}-{it.get('gameId')}",
        "sport": "football",
        "league": league_name,
        "competition": it.get("meetName") or league_name,
        "round": it.get("roundId"),
        "date": d,
        "time": t if len(t) == 5 else None,
        "home": {"name": it.get("homeTeamName"), "code": it.get("homeTeam"), "team_id": home_t and home_t["id"]},
        "away": {"name": it.get("awayTeamName"), "code": it.get("awayTeam"), "team_id": away_t and away_t["id"]},
        "venue": it.get("fieldNameFull") or it.get("fieldName"),
        "broadcast": [c.strip() for c in (it.get("broadcastName") or "").split("//") if c.strip()],
        "status": status,
        "score": [it.get("homeGoal"), it.get("awayGoal")] if status == "종료" else None,
        "info_url": match_url,
    }


def normalize_kbl(it: dict, teams: list[dict]) -> dict | None:
    if int(it.get("seasonGrade") or 1) != 1:  # 1군 경기만
        return None
    basketball = [t for t in teams if t["sport"] == "basketball"]
    home_t = next((t for t in basketball if t.get("kbl_code") == it.get("tcodeH")), None)
    away_t = next((t for t in basketball if t.get("kbl_code") == it.get("tcodeA")), None)
    if not home_t and not away_t:
        return None
    gd = it.get("gameDate") or ""
    gs = it.get("gameStart") or ""
    status = "종료" if str(it.get("isEnded")) == "1" else ("진행 중" if str(it.get("isStarted")) == "1" else "예정")
    return {
        "id": f"kbl-{it.get('gmkey')}",
        "sport": "basketball",
        "league": "KBL",
        "competition": f"KBL {it.get('seasonName1') or ''} {it.get('seasonCategoryName') or ''}".strip(),
        "round": None,
        "date": f"{gd[:4]}-{gd[4:6]}-{gd[6:8]}",
        "time": f"{gs[:2]}:{gs[2:]}" if len(gs) == 4 else None,
        "home": {"name": it.get("tnameH"), "code": it.get("tcodeH"), "team_id": home_t and home_t["id"]},
        "away": {"name": it.get("tnameA"), "code": it.get("tcodeA"), "team_id": away_t and away_t["id"]},
        "venue": it.get("stadiumnameF") or it.get("stadiumname"),
        "broadcast": [c.strip() for c in (it.get("tv") or "").replace("|", ",").split(",") if c.strip()],
        "status": status,
        "score": [it.get("scoreH"), it.get("scoreA")] if status == "종료" else None,
        "info_url": "https://www.kbl.or.kr",
    }


def attach_ticket(game: dict, teams_by_id: dict) -> None:
    """홈팀이 관심팀이면 티켓 오픈 예상 시각과 예매 링크를 붙인다."""
    home_id = game["home"]["team_id"]
    if not home_id:
        game["ticket"] = None
        return
    team = teams_by_id[home_id]
    rule = team.get("ticket_open") or {}
    gdate = date.fromisoformat(game["date"])
    hh, mm = (rule.get("time") or "14:00").split(":")
    open_at = datetime.combine(gdate - timedelta(days=int(rule.get("days_before", 7))),
                               datetime.min.time(), KST).replace(hour=int(hh), minute=int(mm))
    game["ticket"] = {"url": team["ticket_url"], "open_at": open_at.isoformat(), "estimated": True}


def start_dt(game: dict) -> datetime:
    hh, mm = (game["time"] or "19:00").split(":")
    return datetime.combine(date.fromisoformat(game["date"]), datetime.min.time(), KST).replace(
        hour=int(hh), minute=int(mm))


# ---------------------------------------------------------------- ICS

def ics_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line: str) -> str:
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > 73:
            out.append(cur.decode("utf-8"))
            cur = b" "
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n".join(out)


def utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def alarm_lines(minutes_list: list[int], text: str) -> list[str]:
    lines = []
    for m in minutes_list:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(text)}",
                  f"TRIGGER:-PT{int(m)}M", "END:VALARM"]
    return lines


def game_title(g: dict, team_id: str | None = None) -> str:
    sport = "축구" if g["sport"] == "football" else "농구"
    if team_id:
        tag = "홈" if g["home"]["team_id"] == team_id else "원정"
    else:
        tag = "홈" if g["home"]["team_id"] else "원정"
    return f"[{sport}·{tag}] {g['home']['name']} vs {g['away']['name']}"


def build_ics(games: list[dict], cfg: dict, cal_name: str, now: datetime, team_id: str | None = None) -> str:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//sports-alarm//KO", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_escape(cal_name)}", "X-WR-TIMEZONE:Asia/Seoul",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    stamp = utc(now)
    for g in games:
        st = start_dt(g)
        en = st + timedelta(minutes=GAME_MINUTES[g["sport"]])
        desc = [g["competition"], f"장소: {g['venue'] or '-'}"]
        if g["broadcast"]:
            desc.append("중계: " + ", ".join(g["broadcast"]))
        if g.get("ticket"):
            desc.append(f"예매: {g['ticket']['url']}")
        if not g["time"]:
            desc.append("경기 시간 미정 (19:00 임시 표기)")
        lines += ["BEGIN:VEVENT", f"UID:{g['id']}@sports-alarm", f"DTSTAMP:{stamp}",
                  f"DTSTART:{utc(st)}", f"DTEND:{utc(en)}",
                  f"SUMMARY:{ics_escape(game_title(g, team_id))}",
                  f"LOCATION:{ics_escape(g['venue'] or '')}",
                  f"DESCRIPTION:{ics_escape(chr(10).join(desc))}"]
        url = (g.get("ticket") or {}).get("url") or g.get("info_url")
        if url:
            lines.append(f"URL:{url}")
        if g["status"] in ("연기", "취소"):
            lines.append("STATUS:CANCELLED")
        if st > now:
            lines += alarm_lines(cfg["game_alarms_minutes"], game_title(g, team_id))
        lines.append("END:VEVENT")

        t = g.get("ticket")
        if team_id and g["home"]["team_id"] != team_id:
            t = None  # 팀 캘린더에는 그 팀 홈경기 티켓 일정만
        if t and st > now:
            op = datetime.fromisoformat(t["open_at"])
            title = f"[티켓오픈] {g['home']['name']} vs {g['away']['name']} ({st.month}/{st.day})"
            lines += ["BEGIN:VEVENT", f"UID:{g['id']}-ticket@sports-alarm", f"DTSTAMP:{stamp}",
                      f"DTSTART:{utc(op)}", f"DTEND:{utc(op + timedelta(minutes=30))}",
                      f"SUMMARY:{ics_escape(title)}",
                      f"DESCRIPTION:{ics_escape('예매 링크: ' + t['url'] + chr(10) + '오픈 시각은 config.json 규칙으로 계산한 예상값. 구단 공지 확인.')}",
                      f"URL:{t['url']}"]
            if op > now:
                lines += alarm_lines(cfg["ticket_alarms_minutes"], title)
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


# ---------------------------------------------------------------- 메인

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kleague-fixture", help="(테스트용) K리그 응답 JSON 파일")
    ap.add_argument("--kbl-fixture", help="(테스트용) KBL 응답 JSON 파일")
    ap.add_argument("--now", help="(테스트용) 기준 시각 ISO, 예: 2026-03-01T09:00")
    args = ap.parse_args()

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    teams = cfg["teams"]
    teams_by_id = {t["id"]: t for t in teams}
    now = datetime.fromisoformat(args.now).replace(tzinfo=KST) if args.now else datetime.now(KST)
    start = (now - timedelta(days=14)).date()
    end = (now + timedelta(days=int(cfg.get("lookahead_days", 200)))).date()

    if args.kleague_fixture or args.kbl_fixture:
        kl_raw = []
        if args.kleague_fixture:
            p = json.loads(Path(args.kleague_fixture).read_text(encoding="utf-8"))
            kl_raw = (p.get("data", p) or {}).get("scheduleList", [])
        kbl_raw = json.loads(Path(args.kbl_fixture).read_text(encoding="utf-8")) if args.kbl_fixture else []
    else:
        kl_raw = fetch_kleague(start, end)
        kbl_raw = fetch_kbl(start, end)

    games = [g for g in (normalize_kleague(it, teams) for it in kl_raw) if g]
    games += [g for g in (normalize_kbl(it, teams) for it in kbl_raw) if g]
    games = [g for g in games if g["date"] and start <= date.fromisoformat(g["date"]) <= end]
    for g in games:
        attach_ticket(g, teams_by_id)
    games.sort(key=lambda g: (g["date"], g["time"] or "99:99"))

    if not games:
        print("[중단] 가져온 경기가 0건. 기존 파일을 유지한다. (비시즌이거나 API 변경 가능성)", file=sys.stderr)
        return 1

    out = ROOT / "docs"
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "calendar").mkdir(parents=True, exist_ok=True)
    (out / "data" / "games.json").write_text(json.dumps({
        "updated_at": now.isoformat(timespec="minutes"),
        "teams": [{k: t[k] for k in ("id", "name", "sport", "color", "ticket_url")} for t in teams],
        "games": games,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    (out / "calendar" / "all.ics").write_text(build_ics(games, cfg, "직관 일정 (전체)", now), encoding="utf-8", newline="")
    for t in teams:
        mine = [g for g in games if t["id"] in (g["home"]["team_id"], g["away"]["team_id"])]
        (out / "calendar" / f"{t['id']}.ics").write_text(
            build_ics(mine, cfg, f"{t['name']} 일정", now, t["id"]), encoding="utf-8", newline="")

    homes = sum(1 for g in games if g["home"]["team_id"])
    print(f"완료: 경기 {len(games)}건 (관심팀 홈 {homes}건), 기간 {start} ~ {end}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
