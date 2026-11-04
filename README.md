# 직관 캘린더 (K리그 + KBL 관심팀 알림)

관심팀: 수원삼성, 대전하나시티즌, FC서울 / 수원 KT, 안양 정관장, 서울 삼성, 서울 SK

## 하는 일

1. K리그 공식 일정 API(kleague.com)와 KBL 공식 일정 API(api.kbl.or.kr)에서 경기 일정을 가져온다. K리그1/K리그2 둘 다 조회하므로 승격/강등이 있어도 그대로 따라간다.
2. 경기마다 홈/원정을 구분한다.
3. 관심팀 홈경기에는 티켓 오픈 예상 시각과 예매 링크를 붙인다.
4. 결과물
   - `docs/index.html` : 일정 웹페이지 (팀 필터, 홈/원정 필터, 다가오는 티켓 오픈, 예매 버튼)
   - `docs/calendar/all.ics` 및 팀별 `.ics` : 휴대폰 캘린더 구독용. 경기 일정 + "[티켓오픈]" 일정이 들어가고 알람이 박혀 있다
   - 텔레그램 아침 요약 (선택) : 오늘 경기, 오늘/내일 티켓 오픈 + 예매 링크

## GitHub로 자동화 (추천, 무료)

1. GitHub에서 새 저장소 생성 (Public). 이 폴더 내용 전체 업로드.
2. Settings > Pages > Source: `Deploy from a branch`, Branch: `main`, 폴더: `/docs` 저장.
3. Actions 탭 > `update-schedule` > `Run workflow` 한 번 실행. (이후 하루 4번 자동 갱신)
4. 페이지 주소 `https://<아이디>.github.io/<저장소명>/` 접속.
5. 페이지 상단 버튼으로 캘린더 구독.
   - 아이폰: "아이폰 캘린더에 구독" 누름. 설정 화면에서 **"알림 제거" 끄기** (켜져 있으면 알람이 안 울림).
   - 구글 캘린더: 구독 캘린더는 .ics 안의 알람을 무시한다. 구글 캘린더 설정에서 이 캘린더의 "기본 알림"을 직접 지정해야 한다 (예: 10분 전). 티켓오픈이 별도 일정이라 기본 알림만으로 티켓 알림도 같이 온다.

### 텔레그램 알림 켜기 (선택)

1. 텔레그램에서 @BotFather 에게 `/newbot` → 봇 토큰 받기.
2. 만든 봇에게 아무 메시지나 보낸 뒤 `https://api.telegram.org/bot<토큰>/getUpdates` 접속 → `"chat":{"id":숫자}` 확인.
3. 저장소 Settings > Secrets and variables > Actions > New repository secret
   - `TELEGRAM_BOT_TOKEN` = 봇 토큰
   - `TELEGRAM_CHAT_ID` = 위 숫자
4. 매일 오전 8시(KST)쯤 요약이 온다. 알릴 내용이 없는 날은 안 온다.
   GitHub 예약 실행은 수십 분 늦어질 수 있다. 분 단위 정확한 알림은 캘린더 알람이 담당한다.

## GitHub 없이 쓰기

```bash
python3 tracker.py          # docs/ 에 games.json, .ics 생성
python3 notify.py --dry-run # 오늘 알림 내용 미리보기
```
생성된 `docs/calendar/all.ics` 파일을 캘린더 앱에 "가져오기" 하면 된다. 단, 이 방식은 자동 갱신이 안 된다(일정 변경 시 다시 실행 후 다시 가져오기). 웹페이지는 `cd docs && python3 -m http.server` 후 `http://localhost:8000` 접속.

## 설정 바꾸기 (config.json)

- `ticket_open` : 티켓 오픈 규칙. `{"days_before": 7, "time": "14:00"}` = 경기 7일 전 14시.
  **기본값은 추정치다.** 구단마다, 시즌마다, 경기마다(빅매치 선예매 등) 다르다. 각 구단 공지를 보고 숫자를 고쳐라.
- `ticket_url` : 예매 버튼이 여는 주소. 축구는 구단 홈페이지, 농구는 KBL 통합 홈페이지로 넣어 뒀다. 실제 쓰는 예매처(티켓링크, NOL 등) 팀 페이지 주소를 알면 그걸로 바꾸는 게 제일 빠르다.
- `game_alarms_minutes` : 경기 알람 (기본 1440분=하루 전, 180분=3시간 전)
- `ticket_alarms_minutes` : 티켓오픈 알람 (기본 60분 전, 10분 전)
- 팀 추가: K리그는 `kleague_code`(예: 수원FC K29 등, kleague.com 팀 코드), KBL은 `kbl_code` 추가.
  KBL 코드: LG 50, 정관장 70, DB 16, SK 55, 소노 66, KCC 60, KT 06, 현대모비스 10, 가스공사 64, 삼성 35

## 한계

- 코리아컵, ACL, 친선전은 K리그 일정 API에 없으면 안 잡힌다.
- 공식 사이트가 API 구조를 바꾸면 수집이 실패한다. 실패 시 기존 파일을 지우지 않고 유지하며 Actions 로그에 경고가 찍힌다.
- 티켓 오픈 시각은 규칙 기반 예상치다. 예매처 오픈 페이지를 직접 긁어오는 기능은 없다.
