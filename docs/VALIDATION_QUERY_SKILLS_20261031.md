# 독립 데이터 조회 스킬 검증 기록

검증일: 2026-10-31

## 구현 범위

`oracle-query`, `datalake-query`, `ehub-query`, `data-query-demo`를 독립 배포했습니다. 회사 하네스의 스킬, 후크, 개인 Claude 설정이나 기존 MCP는 변경하지 않았습니다. 플랫폼 ZIP 규격은 로컬 정본 `pt_ai_square/static/guides/pt-file-distribution/SKILL.md`를 사용했습니다. ZIP 생성은 게시나 개인 설치와 별개입니다.

공통 실행 코드는 `scripts/query_skills/query_core`가 정본이며 `scripts/sync-query-skills.py`로 네 배포 원본에 복제합니다. 각 ZIP에는 필요한 자체 코드가 들어 있습니다. Python 라이브러리는 requirements.txt의 외부 의존성으로 명시합니다.

## 확인한 결과

- 등록 이름 표시: `1. 생산실적조회 — 생산DB`, `2. 생산실적조회 — 품질DB`
- 연결과 쿼리 등록은 실행을 일으키지 않으며 저장소를 다시 열어도 번호와 내용 유지
- 일반 기간 조회는 조건 확인만 필요하며 ORDER BY만으로 큰 조회 승인을 요구하지 않음
- 기간과 공정 변경에 따라 합성 데이터의 실제 행과 합계가 바뀜
- 같은 조건을 다른 DB 프로필에서 실행하면 해당 합성 DB의 결과 사용
- 12,005행 조회는 승인 없이 실행하지 않고, 20,000행으로 확대하여 승인하면 전체 저장
- SQL, 연결, 접속 정보 변경 및 15분 경과 시 이전 계획 거부, 이미 실행한 계획 중복 실행 방지
- 누락 조건과 자료형 오류는 연결 전에 안내, 값은 SQL 문자열에 합치지 않고 바인드 처리
- 0건, 일부 저장, 완전한 결과, 오류를 구분
- JSONL 행 배열로 중복 열 이름, 앞자리 0과 정밀 소수 보존. Oracle NUMBER는 해당 커서에서 Decimal로 수신하도록 구성
- 100KB를 넘는 긴 컬럼명 메타데이터도 결과 확인과 CSV 내보내기 가능
- CSV의 수식 형태 문자열은 표시용 내보내기에서만 보호하고 원본 JSONL 유지
- 모델용 응답에는 원본 행을 넣지 않음. 긴 조건 목록은 요약 여부와 전체 조건의 로컬 검토 파일을 명시
- 더미 실행은 운영 인증정보를 읽지 않고 네트워크 연결 없이 수행
- 운영 어댑터의 호출 순서, 바인드, 제한, 오류 정리와 연결 해제는 가짜 드라이버로 검증
- 배포 ZIP을 각각 임시 폴더에 풀어 기존 하네스 및 다른 스킬 경로 없이 진입점 실행
- 실제 배포된 더미 ZIP의 초기화, 목록, 등록, 조건 준비, 실행, 결과 확인, CSV 저장과 확대 조회를 별도 Python 프로세스로 검증

## 검사 명령

```powershell
python -X utf8 -B -m unittest discover -s tests/query_skills -q
python -X utf8 -B -m unittest tests.test_query_skill_packages tests.test_platform_skill_packages -q
python -X utf8 -B scripts/sync-query-skills.py --check
python -X utf8 -B scripts/build-skill-packages.py --check
```

실행 로직 검사 82개와 패키지 검사 51개, 총 133개가 통과했습니다. 동기화 검사와 17개 전체 배포 ZIP의 최신 상태 검사도 통과했습니다. Windows 샌드박스의 기본 임시 폴더가 쓰기를 거부하는 환경에서는 검사 프로세스의 TEMP와 TMP만 저장소 `.smoke`로 지정했습니다. 운영 환경변수는 변경하지 않았습니다. ZIP 실행 검사는 `-E -P`로 PYTHONPATH와 현재 폴더의 암묵적 검색을 배제하되 설치된 requirements 라이브러리는 사용합니다.

## 확인하지 않은 범위

사내 DB 접속, 실제 Oracle/StarRocks 서버의 SQL 호환성, S3 키 없는 LakeHouse 접속, 실제 E-HUB 테이블 제공 범위, 운영 네트워크와 인증서 및 회사 모델의 대화 수행은 검증하지 않았습니다. 로컬 설정창의 실제 사용자 조작과 여러 화면 배율에서의 시각 검증도 포함하지 않았습니다.

더미 정확한 건수는 합성 자료에서만 계산합니다. 운영에서 전체 COUNT나 EXPLAIN ANALYZE를 자동 실행하지 않습니다. Oracle의 사전 건수는 미확인으로 남을 수 있습니다. LakeHouse의 계획 단계 최대 추정량을 결과 행 수라고 표시하지 않습니다. 출력 제한과 취소 요청은 DB 서버의 모든 작업이 즉시 종료된다는 보장이 아닙니다.

승인 플래그는 사용자의 실제 대답을 따르도록 스킬에 명시하고 실행 계획에 묶지만, 사용자 신원을 독립적으로 인증하는 승인지원 시스템은 아닙니다. 접속 env 파일은 로컬 평문이며 암호화 저장을 보장하지 않습니다.

자료형 처리 근거: [python-oracledb 3.3 숫자 정밀도와 출력 핸들러](https://python-oracledb.readthedocs.io/en/v3.3.0/user_guide/sql_execution.html#fetched-number-precision), [mysql.connector 커서의 실제 바인드 처리](https://github.com/mysql/mysql-connector-python/blob/trunk/mysql-connector-python/lib/mysql/connector/cursor.py).
